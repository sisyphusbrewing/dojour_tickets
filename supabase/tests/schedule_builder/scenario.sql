\set ON_ERROR_STOP 0
\set sam '00000000-0000-0000-0000-000000000001'
\set mgr '00000000-0000-0000-0000-000000000002'
\set dee '00000000-0000-0000-0000-000000000003'
\set bld '00000000-0000-0000-0000-000000000004'
\set door '00000000-0000-0000-0000-000000000005'
-- Every check prints "ok" or "FAIL". Lines marked (expect ERROR) are meant to fail.
-- bld is the staff login that gets the "builds the schedule" mark, dee a
-- coworker with a plain staff login. The days are worked out from today, so
-- this passes whatever day it is run.
select schedule_today() + 1 as d1, schedule_today() + 2 as d2, schedule_today() + 3 as d3,
       schedule_today() + 10 as d10, schedule_today() + 12 as d12,
       schedule_monday(schedule_today()) + 14 as w2, schedule_monday(schedule_today()) + 21 as w3 \gset
-- Thanksgiving 2026 comes with the staffing rules as a day set to nobody. Put
-- it back to the rules here so it can't land on one of the test days.
update staffing_days set people = null where day = '2026-11-26';
-- Supabase hands every table to the website's logins and leaves it to the
-- row rules to say no. Copy that here for the logins table, so "a login
-- cannot give itself the mark" is proved by the row rules.
grant all on public.staff_roles to anon, authenticated;

\echo == what the file changed: each of the eight functions asks can_schedule and none still asks is_manager
select case when count(*) = 8 and count(*) filter (where pg_get_functiondef(p.oid) like '%public.can_schedule()%'
                                                      and pg_get_functiondef(p.oid) not like '%public.is_manager()%') = 8
            then 'ok' else 'FAIL' end as eight_rewritten
  from pg_proc p join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = 'public' and p.proname in ('schedule_people', 'schedule_set_person', 'schedule_publish', 'schedule_needs',
       'schedule_need_set', 'schedule_usual', 'schedule_usual_fill', 'schedule_usual_save');
\echo == changing the numbers behind the staffing lines still asks for a manager
select case when pg_get_functiondef('public.schedule_needs_rules(int,int,int,int,int,int)'::regprocedure) like '%public.is_manager()%'
            then 'ok' else 'FAIL' end as rules_left_alone;

set role authenticated; select set_config('request.jwt.claim.sub', :'bld', false);

\echo == before the mark, a staff login may not build
select case when not can_schedule() then 'ok' else 'FAIL' end as not_yet;
\echo (expect ERROR: row-level security, a staff login adding a shift)
insert into shifts (work_date, start_time, position) values (:'d1', '16:00', 'Bar');
\echo (expect ERROR: Managers only, a staff login posting)
select schedule_publish(:'d1', :'d3');

\echo == a login cannot give itself the mark, or read the logins table
update staff_roles set builds_schedule = true where user_id = :'bld';
select case when count(*) = 0 then 'ok' else 'FAIL' end as cannot_read_logins from staff_roles;
reset role;
select case when not builds_schedule then 'ok' else 'FAIL' end as cannot_mark_itself from staff_roles where user_id = :'bld';

\echo == the mark is set in the database, on the owner's word
update staff_roles set builds_schedule = true where user_id = :'bld';
set role authenticated; select set_config('request.jwt.claim.sub', :'bld', false);
select case when can_schedule() and not is_manager() then 'ok' else 'FAIL' end as builds_but_is_no_manager;

\echo == builds a week: drafts for a coworker, for themselves and an open one; sees them; nobody is told
insert into shifts (work_date, start_time, end_time, position, user_id) values
 (:'d1', '15:30', '22:30', 'Bar', :'dee'),
 (:'d2', '15:30', '23:30', 'Bar', :'bld'),
 (:'d2', '18:00', '23:30', 'Bar', null),
 (:'d3', '12:30', '17:30', 'Bar', :'dee');
select case when count(*) = 4 then 'ok' else 'FAIL' end as sees_the_drafts from shifts;
reset role;
select case when count(*) = 0 then 'ok' else 'FAIL' end as drafts_are_quiet from schedule_outbox;
\echo == a plain staff login still sees no drafts
set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
select case when count(*) = 0 then 'ok' else 'FAIL' end as staff_see_no_drafts from shifts;

\echo == posts the week: four shifts; the coworker is told theirs, the builder is not told their own post
select set_config('request.jwt.claim.sub', :'bld', false);
select case when schedule_publish(:'d1', :'d3') = 4 then 'ok' else 'FAIL' end as posted_four;
reset role;
select case when count(*) filter (where user_id = :'dee' and kind = 'published') = 1
             and count(*) filter (where user_id = :'bld') = 0 then 'ok' else 'FAIL' end as told_on_post from schedule_outbox;

\echo == changes a posted shift: its person is told. Removes one.
set role authenticated; select set_config('request.jwt.claim.sub', :'bld', false);
update shifts set start_time = '16:00' where work_date = :'d1';
delete from shifts where work_date = :'d3';
select case when count(*) = 3 then 'ok' else 'FAIL' end as removed_one from shifts;
reset role;
select case when count(*) = 1 then 'ok' else 'FAIL' end as told_on_change from schedule_outbox where user_id = :'dee' and kind = 'shift_changed';

\echo == a coworker asks for time off: the manager and the builder are told, the owner is not
set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
insert into time_off (start_date, end_date, note) values (:'d10', :'d12', 'wedding');
reset role;
select case when count(*) filter (where user_id = :'mgr') = 1 and count(*) filter (where user_id = :'bld') = 1
             and count(*) filter (where user_id = :'sam') = 0 then 'ok' else 'FAIL' end as asked_and_told
  from schedule_outbox where kind = 'timeoff_asked';
\echo == the builder sees the request and approves it; the coworker is told
set role authenticated; select set_config('request.jwt.claim.sub', :'bld', false);
select case when count(*) = 1 then 'ok' else 'FAIL' end as sees_the_request from time_off;
update time_off set status = 'approved', decided_by = 'Builder', decided_at = now() where user_id = :'dee';
reset role;
select case when (select status from time_off where user_id = :'dee') = 'approved'
             and (select count(*) from schedule_outbox where user_id = :'dee' and kind = 'timeoff_approved') = 1
            then 'ok' else 'FAIL' end as approved_and_told;

\echo == the builder's own request: they cannot approve it (expect ERROR: row-level security)
set role authenticated; select set_config('request.jwt.claim.sub', :'bld', false);
insert into time_off (start_date, end_date) values (:'d10', :'d10');
update time_off set status = 'approved', decided_by = 'Builder', decided_at = now() where user_id = :'bld';
reset role;
select case when status = 'pending' then 'ok' else 'FAIL' end as own_request_still_waiting from time_off where user_id = :'bld';
\echo == a manager approves it, and the builder can still take it back
set role authenticated; select set_config('request.jwt.claim.sub', :'mgr', false);
update time_off set status = 'approved', decided_by = 'Manager', decided_at = now() where user_id = :'bld';
select set_config('request.jwt.claim.sub', :'bld', false);
update time_off set status = 'cancelled' where user_id = :'bld';
reset role;
select case when status = 'cancelled' then 'ok' else 'FAIL' end as took_own_back from time_off where user_id = :'bld';

\echo == the days a coworker cannot work: the builder sees them and is told when they change
set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
insert into staff_availability (user_id, off_days, note) values (:'dee', '{1}', 'class');
select set_config('request.jwt.claim.sub', :'bld', false);
select case when count(*) = 1 then 'ok' else 'FAIL' end as sees_days_off from staff_availability;
reset role;
select case when count(*) = 1 then 'ok' else 'FAIL' end as told_days_off from schedule_outbox where user_id = :'bld' and kind = 'availability';

\echo == how many people a day needs: the builder gets the numbers and sets one day by hand
set role authenticated; select set_config('request.jwt.claim.sub', :'bld', false);
select case when (schedule_needs(:'d1', :'d3') -> 'days' -> 0) ? 'people' then 'ok' else 'FAIL' end as gets_the_numbers;
select schedule_need_set(:'d2', 0, 'Private party');
select case when (schedule_needs(:'d2', :'d2') -> 'days' -> 0 ->> 'people')::int = 0 then 'ok' else 'FAIL' end as set_one_day;
select schedule_need_set(:'d2', null);
\echo (expect ERROR: Managers only, the numbers behind the lines stay with managers)
select schedule_needs_rules(1, 1, 1, 0, 60, 90);
\echo == a plain staff login gets the day's events and no numbers
select set_config('request.jwt.claim.sub', :'dee', false);
select case when not ((schedule_needs(:'d1', :'d3') -> 'days' -> 0) ? 'people') then 'ok' else 'FAIL' end as staff_get_no_numbers;

\echo == the usual week: the builder saves a week as it, lists it and fills the week after from it
select set_config('request.jwt.claim.sub', :'bld', false);
insert into shifts (work_date, start_time, end_time, position, user_id) values
 (:'w2'::date + 1, '15:30', '22:30', 'Bar', :'bld'),
 (:'w2'::date + 2, '15:30', '22:30', 'Bar', :'dee');
select case when schedule_usual_save(:'w2') = 2 then 'ok' else 'FAIL' end as saved_usual_week;
select case when jsonb_array_length(schedule_usual()) = 2 then 'ok' else 'FAIL' end as lists_usual_week;
select case when (schedule_usual_fill(:'w3') ->> 'added')::int = 2 then 'ok' else 'FAIL' end as filled_from_it;

\echo == names and who is on the schedule: the builder sets them, and sees the logins that are switched off
select schedule_set_person(:'dee', 'Dee Example', true);
select case when (select count(*) from schedule_people() where not on_schedule) >= 1
             and (select name from schedule_people() where user_id = :'dee') = 'Dee Example' then 'ok' else 'FAIL' end as sets_people;

\echo == the time clock's notices to managers do not go to the builder
reset role;
select schedule_tell_group(false, null, 'clock_typed', 'x');
select case when count(*) filter (where user_id = :'mgr') = 1 and count(*) filter (where user_id = :'bld') = 0
            then 'ok' else 'FAIL' end as clock_news_is_managers_only from schedule_outbox where kind = 'clock_typed';

\echo == a plain staff login is refused all of it (expect ERROR four times: a shift, posting, the usual week, a day by hand)
set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
insert into shifts (work_date, start_time, position) values (:'d1', '16:00', 'Bar');
select schedule_publish(:'d1', :'d3');
select schedule_usual_fill(:'w3');
select schedule_need_set(:'d2', 2);
select case when count(*) filter (where user_id <> :'dee') = 0 and count(*) = 1 then 'ok' else 'FAIL' end as staff_see_only_own_time_off from time_off;

\echo == the mark does nothing for a door login
reset role;
update staff_roles set builds_schedule = true where user_id = :'door';
set role authenticated; select set_config('request.jwt.claim.sub', :'door', false);
select case when not can_schedule() then 'ok' else 'FAIL' end as never_a_door_login;

\echo == the mark comes off: a staff login again, drafts out of sight
reset role;
update staff_roles set builds_schedule = false where user_id = :'bld';
set role authenticated; select set_config('request.jwt.claim.sub', :'bld', false);
select case when not can_schedule() and (select count(*) from shifts where not published) = 0 then 'ok' else 'FAIL' end as mark_off;

\echo == managers and the owner build as before; signed out, nobody does
select set_config('request.jwt.claim.sub', :'mgr', false);
select case when can_schedule() and (select count(*) from shifts where not published) = 4 then 'ok' else 'FAIL' end as manager_as_before;
select set_config('request.jwt.claim.sub', :'sam', false);
select case when can_schedule() then 'ok' else 'FAIL' end as owner_as_before;
select set_config('request.jwt.claim.sub', '', false);
select case when not coalesce(can_schedule(), false) then 'ok' else 'FAIL' end as signed_out;
