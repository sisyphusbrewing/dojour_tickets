\set ON_ERROR_STOP 0
\set sam '00000000-0000-0000-0000-000000000001'
\set mgr '00000000-0000-0000-0000-000000000002'
\set dee '00000000-0000-0000-0000-000000000003'
\set bld '00000000-0000-0000-0000-000000000004'
\set door '00000000-0000-0000-0000-000000000005'
-- Every check prints "ok" or "FAIL". Lines marked (expect ERROR) are meant to fail.
-- Days are worked out from today, so this passes whatever day it is run.
select schedule_today() + 1 as d1, schedule_today() + 2 as d2, schedule_today() + 3 as d3,
       schedule_today() - 90 as old \gset
update staff_roles set display_name = 'Dee Stork' where user_id = :'dee';
update staff_roles set display_name = 'Jo Warren' where user_id = :'bld';
-- d1: Dee 4 PM to 10 PM, Jo works too. d2: Dee until close. d3: a draft
-- (never on the calendar). old: long past (left off). Jo's own shift on d1.
insert into shifts (work_date, start_time, end_time, position, user_id, published, note) values
  (:'d1', '16:00', '22:00', 'Bar', :'dee', true, 'Two shows tonight'),
  (:'d1', '17:00', '23:00', 'Door', :'bld', true, ''),
  (:'d2', '20:00', null, 'Bar', :'dee', true, ''),
  (:'d2', '22:00', '01:00', 'Barback', :'bld', true, ''),
  (:'d3', '16:00', '21:00', 'Bar', :'dee', false, ''),
  (:'old', '16:00', '21:00', 'Bar', :'dee', true, '');

set role authenticated;
\echo (expect ERROR: Please sign in again, nobody signed in)
select my_calendar_feed();
select set_config('request.jwt.claim.sub', :'door', false);
\echo (expect ERROR: Staff only, the door login)
select my_calendar_feed();
\echo (expect ERROR: permission denied, a login reading the codes)
select * from calendar_feeds;

select set_config('request.jwt.claim.sub', :'dee', false);
select my_calendar_feed() as tok \gset
\echo == a staff login gets a 32-letter code, the same one each time
select case when :'tok' ~ '^[a-f0-9]{32}$' and my_calendar_feed() = :'tok' then 'ok' else 'FAIL' end as same_code;
\echo (expect ERROR: permission denied, a login reading the calendar itself)
select schedule_calendar(:'tok');

reset role;
set role service_role;
select schedule_calendar(:'tok') as cal \gset
reset role;
\echo == the calendar shows the two posted shifts and nothing else
select case when jsonb_array_length((:'cal')::jsonb -> 'shifts') = 2 then 'ok' else 'FAIL' end as two_shifts;
\echo == 4 to 10 PM in Minneapolis time, with its note and who else works
select case when s ->> 'starts' = to_char(:'d1'::date, 'YYYYMMDD') || 'T160000'
             and s ->> 'ends' = to_char(:'d1'::date, 'YYYYMMDD') || 'T220000'
             and s ->> 'note' = 'Two shows tonight' and s -> 'with' = '["Jo"]'::jsonb
            then 'ok' else 'FAIL' end as first_shift
  from jsonb_array_elements((:'cal')::jsonb -> 'shifts') s where s ->> 'position' = 'Bar' and s ->> 'starts' like to_char(:'d1'::date, 'YYYYMMDD') || '%';
\echo == until close ends at the closing time from the staffing settings
select case when s ->> 'until_close' = 'true'
             and s ->> 'ends' = to_char(:'d2'::date + ((select hours from staffing_settings) -> lower(to_char(:'d2'::date, 'Dy')) ->> 1)::time, 'YYYYMMDD"T"HH24MISS')
            then 'ok' else 'FAIL' end as until_close
  from jsonb_array_elements((:'cal')::jsonb -> 'shifts') s where s ->> 'starts' like to_char(:'d2'::date, 'YYYYMMDD') || '%';

set role authenticated; select set_config('request.jwt.claim.sub', :'bld', false);
select my_calendar_feed() as jtok \gset
reset role;
set role service_role;
select schedule_calendar(:'jtok') as jcal \gset
reset role;
\echo == a shift past midnight ends the next morning
select case when s ->> 'ends' = to_char(:'d2'::date + 1, 'YYYYMMDD') || 'T010000' then 'ok' else 'FAIL' end as past_midnight
  from jsonb_array_elements((:'jcal')::jsonb -> 'shifts') s where s ->> 'position' = 'Barback';
\echo == a shift handed to someone else leaves the calendar
update shifts set user_id = :'bld' where work_date = :'d1' and user_id = :'dee';
set role service_role;
select case when jsonb_array_length(schedule_calendar(:'tok') -> 'shifts') = 1 then 'ok' else 'FAIL' end as handed_on;
reset role;

\echo == a new link stops the old one
set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
select my_calendar_feed(true) as tok2 \gset
reset role; set role service_role;
select case when :'tok2' <> :'tok' and schedule_calendar(:'tok') is null and schedule_calendar(:'tok2') is not null
            then 'ok' else 'FAIL' end as new_link;
\echo == an unknown or badly formed code shows nothing
select case when schedule_calendar('0123456789abcdef0123456789abcdef') is null and schedule_calendar('nope') is null
                 and schedule_calendar(null) is null then 'ok' else 'FAIL' end as unknown;
reset role;
\echo == a login that is no longer staff loses its calendar
update staff_roles set role = 'door' where user_id = :'dee';
set role service_role;
select case when schedule_calendar(:'tok2') is null then 'ok' else 'FAIL' end as not_staff;
reset role;
update staff_roles set role = 'staff' where user_id = :'dee';
