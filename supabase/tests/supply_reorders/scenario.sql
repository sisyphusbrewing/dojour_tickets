-- Checks for the reorder buttons (20261117220000_supply_reorders.sql).
-- Each check prints ok or FAIL. Steps that are meant to be refused say how
-- many ERRORs to expect just above them.
\set ON_ERROR_STOP 0
\set owner   '''{"sub":"00000000-0000-0000-0000-000000000001"}'''
\set manager '''{"sub":"00000000-0000-0000-0000-000000000002"}'''
\set staff   '''{"sub":"00000000-0000-0000-0000-000000000003"}'''
\set door    '''{"sub":"00000000-0000-0000-0000-000000000005"}'''

update staff_roles set display_name = 'Grace' where user_id = '00000000-0000-0000-0000-000000000002';

select case when count(*) = 6 then 'ok' else 'FAIL' end || ' six buttons to start' from supply_reorders;

-- The email text, built from the parts.
select case when public.reorder_email_body('Hey Andy,', 'We need:',
  '[{"qty":6,"unit":"cases","item":"Root Beer"},{"qty":0,"unit":"cases","item":"Orange"},{"qty":2.5,"unit":"","item":"Lime"}]',
  'Back door please.', 'Sam')
  = E'Hey Andy,\n\nWe need:\n6 cases Root Beer\n2.5 Lime\n\nBack door please.\n\nThanks much!\nSam'
  then 'ok' else 'FAIL' end || ' email skips zero lines, keeps the note, signs Sam';

set role authenticated;

-- Staff can see the buttons and the preview, but not send.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000003', false);
select case when count(*) = 6 then 'ok' else 'FAIL' end || ' staff see the buttons' from supply_reorders;
select case when body like E'Hi there,\n\nCan we get a snack order%1 case of each pretzel flavor%' then 'ok' else 'FAIL' end || ' staff see the pretzel preview'
  from reorder_preview((select id from supply_reorders where label = 'Pretzels'));
\echo 'expect 1 ERROR: staff cannot send'
select place_reorder((select id from supply_reorders where label = 'Pretzels'));
\echo 'expect 1 ERROR: nobody writes orders straight into the table'
insert into supply_orders (reorder_id, to_email, subject, body, lines)
  select id, 'someone@example.com', 'x', 'x', '[]' from supply_reorders limit 1;

-- The door login sees nothing.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000005', false);
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' door sees no buttons' from supply_reorders;

-- Grace sends sodas with Root Beer bumped to 8 and Lime skipped.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
select case when status = 'queued' and to_email = 'amiska@capitolbeverage.com'
             and body like '%8 cases Spring Grove Root Beer%'
             and body not like '%Lime Liquid Death%'
             and body like E'%Thanks much!\nGrace\nSisyphus'
             and ordered_by_name = 'Grace'
  then 'ok' else 'FAIL' end || ' manager sends sodas with changed counts, signed Grace'
  from place_reorder((select id from supply_reorders where label = 'Sodas & Liquid Death'),
                     '[{"item":"Spring Grove Root Beer","qty":8},{"item":"Lime Liquid Death","qty":0}]');

\echo 'expect 1 ERROR: the same button again inside three days'
select place_reorder((select id from supply_reorders where label = 'Sodas & Liquid Death'));
select case when status = 'queued' then 'ok' else 'FAIL' end || ' ...unless she says send it again'
  from place_reorder((select id from supply_reorders where label = 'Sodas & Liquid Death'), null, null, true);

-- Item names can't be changed from the page, only counts.
select case when body not like '%Free money%' and body like '%5 kegs Sisyphus 10% seltzer%' then 'ok' else 'FAIL' end
       || ' a made-up item is ignored'
  from place_reorder((select id from supply_reorders where label = 'Seltzer kegs'), '[{"item":"Free money","qty":99}]');

\echo 'expect 1 ERROR: every count zero'
select place_reorder((select id from supply_reorders where label = 'Pretzels'), '[{"item":"pretzel flavor","qty":0}]');

\echo 'expect 1 ERROR: managers cannot change a button straight in the table'
update supply_reorders set to_email = 'someone@example.com' where label = 'Pretzels';

-- Sam's own login signs "Sam".
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
select case when body like E'%Thanks much!\nSam' then 'ok' else 'FAIL' end || ' owner signs Sam'
  from place_reorder((select id from supply_reorders where label = 'Pretzels'));

reset role;
select case when count(*) = 4 then 'ok' else 'FAIL' end || ' four orders waiting to send' from supply_orders where status = 'queued';
select case when (select to_email from supply_reorders where label = 'Pretzels') = 'businessoffice@vonhansonssnacks.com'
  then 'ok' else 'FAIL' end || ' pretzel address unchanged';
