\set ON_ERROR_STOP 0
\set grace '00000000-0000-0000-0000-000000000002'
\set darrin '00000000-0000-0000-0000-000000000003'
\set jaz '00000000-0000-0000-0000-000000000004'
\set door '00000000-0000-0000-0000-000000000005'
\echo == people as staff (expect grace, darrin, jaz; no door/ticketing)
set role authenticated; select set_config('request.jwt.claim.sub', :'darrin', false);
select username, name, role, on_schedule from schedule_people();
\echo == staff cannot insert a shift (expect RLS error)
insert into shifts (work_date, start_time, position) values (schedule_today()+1, '16:00', 'Bar');
\echo == manager builds drafts
select set_config('request.jwt.claim.sub', :'grace', false);
select schedule_set_person(:'darrin', 'Darrin Stork', true);
insert into shifts (work_date, start_time, end_time, position, user_id) values
 (schedule_today()+1, '16:00', null, 'Bar', :'darrin'),
 (schedule_today()+2, '18:00', '22:00', 'Door', :'jaz'),
 (schedule_today()+2, '16:00', '23:00', 'Bar', null),
 (schedule_today(), '13:00', '18:00', 'Bar', :'jaz');
select count(*) as outbox_after_drafts from schedule_outbox;
\echo == staff sees no drafts (expect 0)
select set_config('request.jwt.claim.sub', :'darrin', false);
select count(*) from shifts;
\echo == staff cannot publish
select schedule_publish(schedule_today(), schedule_today()+6);
\echo == manager publishes (expect 4)
select set_config('request.jwt.claim.sub', :'grace', false);
select schedule_publish(schedule_today(), schedule_today()+6);
reset role; select schedule_name(user_id), kind, body from schedule_outbox order by id; set role authenticated;
\echo == darrin sees 4, own notices only
select set_config('request.jwt.claim.sub', :'darrin', false);
select count(*) from shifts; select count(*) as my_notices from schedule_outbox;
\echo == darrin cannot take jaz's shift (not offered)
select shift_take((select id from shifts where position='Door'));
\echo == jaz offers door shift; darrin takes it; second take fails
select set_config('request.jwt.claim.sub', :'jaz', false);
select shift_offer((select id from shifts where position='Door'), true);
select set_config('request.jwt.claim.sub', :'darrin', false);
select shift_offer((select id from shifts where position='Door'), false);
select shift_take((select id from shifts where position='Door'));
select shift_take((select id from shifts where position='Door'));
\echo == darrin takes the open shift
select shift_take((select id from shifts where user_id is null));
\echo == door login can't take or see
select set_config('request.jwt.claim.sub', :'door', false);
select count(*) from shifts;
\echo == manager edits a published shift time -> darrin told; reassign -> both told; delete -> told
select set_config('request.jwt.claim.sub', :'grace', false);
update shifts set start_time='17:00' where position='Door';
update shifts set user_id = :'jaz' where position='Door';
delete from shifts where position='Door';
\echo == time off: jaz asks, cannot approve own, grace approves
select set_config('request.jwt.claim.sub', :'jaz', false);
insert into time_off (start_date, end_date, note) values (schedule_today()+10, schedule_today()+12, 'wedding');
update time_off set status='approved';
select status from time_off;
select set_config('request.jwt.claim.sub', :'darrin', false);
select count(*) as darrin_sees_timeoff from time_off;
select set_config('request.jwt.claim.sub', :'grace', false);
update time_off set status='approved', decided_by='Grace', decided_at=now();
select set_config('request.jwt.claim.sub', :'jaz', false);
update time_off set status='cancelled';
select status from time_off;
\echo == availability upsert
insert into staff_availability (user_id, off_days, note) values (:'jaz', '{2,3}', 'class Tue/Wed') on conflict (user_id) do update set off_days = excluded.off_days, note = excluded.note;
insert into staff_availability (user_id, off_days, note) values (:'darrin', '{1}', 'x');
select set_config('request.jwt.claim.sub', :'grace', false);
select count(*) as avail_rows_manager from staff_availability;
\echo == save me
select set_config('request.jwt.claim.sub', :'jaz', false);
select schedule_save_me('text', '', '');
select schedule_save_me('both', 'Jaz@Example.com', '(612) 555-0100');
select * from schedule_me();
select schedule_dismiss(array(select id from schedule_outbox));
\echo == reminders + pending (service only)
select schedule_queue_reminders();
reset role; set role service_role;
select schedule_queue_reminders(); select schedule_queue_reminders();
select id, kind, name, notify_by, notify_email, notify_phone, left(body,70) from schedule_outbox_pending();
reset role;
\echo == full outbox
select schedule_name(user_id), kind, body from schedule_outbox order by id;
