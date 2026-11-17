\set ON_ERROR_STOP 0
\set sam '00000000-0000-0000-0000-000000000001'
\set mgr '00000000-0000-0000-0000-000000000002'
\set dee '00000000-0000-0000-0000-000000000003'
\set jaz '00000000-0000-0000-0000-000000000004'
\set door '00000000-0000-0000-0000-000000000005'
-- Every check prints "ok" or "FAIL". Lines marked (expect ERROR) are meant to fail.
-- The weeks are worked out from today, so this passes whatever day it is run:
-- w0 is the Monday of this week, w1 the Monday after, and so on.
select schedule_monday(schedule_today()) as w0, schedule_monday(schedule_today()) + 7 as w1,
       schedule_monday(schedule_today()) + 14 as w2, schedule_monday(schedule_today()) + 21 as w3,
       schedule_monday(schedule_today()) + 28 as w4, schedule_monday(schedule_today()) + 35 as w5,
       schedule_monday(schedule_today()) - 14 as gone \gset
-- Thanksgiving 2026 comes with the staffing rules as a day set to nobody. Put
-- it back to the rules here so it can't land on one of the test days.
update staffing_days set people = null where day = '2026-11-26';

\echo == the Monday of a week, from any day in it
select case when schedule_monday(date '2026-11-17') = date '2026-11-16' and schedule_monday(date '2026-11-22') = date '2026-11-16'
             and schedule_monday(date '2026-11-16') = date '2026-11-16' then 'ok' else 'FAIL' end as monday_of;

set role authenticated; select set_config('request.jwt.claim.sub', :'mgr', false);

\echo == before anything is saved: the usual week is empty, and there is nothing to fill with (expect ERROR: no usual week saved yet)
select case when schedule_usual() = '[]'::jsonb then 'ok' else 'FAIL' end as empty_to_start;
select schedule_usual_fill(:'w1');
\echo == a week with no shifts is not saved as the usual week (expect ERROR: no shifts to save)
select schedule_usual_save(:'w1');

\echo == the manager builds next week by hand: seven shifts, one of them open
insert into shifts (work_date, start_time, end_time, position, user_id, note) values
 (:'w1'::date + 1, '15:30', '22:30', 'Bar', :'mgr', ''),            -- Tuesday
 (:'w1'::date + 2, '15:30', null,    'Bar', :'dee', ''),            -- Wednesday, until close
 (:'w1'::date + 4, '12:30', '17:30', 'Bar', :'dee', ''),            -- Friday day
 (:'w1'::date + 4, '17:30', '23:30', 'Bar', :'mgr', ''),            -- Friday night, two people
 (:'w1'::date + 4, '17:30', '23:30', 'Bar', :'jaz', ''),
 (:'w1'::date + 5, '18:00', null,    'Bar', null,   'Open mic'),    -- Saturday, nobody on it yet
 (:'w1'::date + 6, '12:30', '18:30', 'Bar', :'dee', '');            -- Sunday

\echo == saved as the usual week from any day in that week: seven shifts, Monday first, the people and the open one kept
select case when schedule_usual_save(:'w1'::date + 3) = 7 then 'ok' else 'FAIL' end as saved_seven;
select case when jsonb_array_length(u) = 7
             and (u -> 0 ->> 'weekday')::int = 2 and (u -> 0 ->> 'user_id') = :'mgr' and (u -> 0 ->> 'start_time') = '15:30:00'
             and (u -> 1 ->> 'weekday')::int = 3 and (u -> 1 ->> 'end_time') is null
             and (u -> 5 ->> 'weekday')::int = 6 and (u -> 5 ->> 'user_id') is null and (u -> 5 ->> 'note') = 'Open mic'
             and (u -> 6 ->> 'weekday')::int = 0 and (u -> 6 ->> 'user_id') = :'dee'
            then 'ok' else 'FAIL' end as usual_week_listed
  from (select schedule_usual() as u) x;

\echo == filling the week after: the same seven shifts on the right days, all drafts, same people
select schedule_usual_fill(:'w2') as r \gset
select case when (:'r'::jsonb ->> 'added')::int = 7 and jsonb_array_length(:'r'::jsonb -> 'open') = 0
             and jsonb_array_length(:'r'::jsonb -> 'days_kept') = 0 and jsonb_array_length(:'r'::jsonb -> 'days_closed') = 0
             and jsonb_array_length(:'r'::jsonb -> 'days_past') = 0 then 'ok' else 'FAIL' end as filled_seven;
select case when count(*) = 7 and count(*) filter (where published) = 0
             and count(*) filter (where work_date = :'w2'::date + 1 and user_id = :'mgr' and start_time = '15:30' and end_time = '22:30') = 1
             and count(*) filter (where work_date = :'w2'::date + 2 and user_id = :'dee' and end_time is null) = 1
             and count(*) filter (where work_date = :'w2'::date + 4) = 3
             and count(*) filter (where work_date = :'w2'::date + 5 and user_id is null and note = 'Open mic') = 1
             and count(*) filter (where work_date = :'w2'::date + 6 and user_id = :'dee' and end_time = '18:30') = 1
            then 'ok' else 'FAIL' end as right_days_all_drafts
  from shifts where work_date between :'w2'::date and :'w2'::date + 6;

\echo == tapped twice: nothing is added again, every day is left alone
select schedule_usual_fill(:'w2'::date + 5) as r \gset
select case when (:'r'::jsonb ->> 'added')::int = 0 and jsonb_array_length(:'r'::jsonb -> 'days_kept') = 5 then 'ok' else 'FAIL' end as twice_adds_nothing;
select case when count(*) = 7 then 'ok' else 'FAIL' end as still_seven from shifts where work_date between :'w2'::date and :'w2'::date + 6;

\echo == nobody is told about drafts
reset role;
select case when count(*) = 0 then 'ok' else 'FAIL' end as nobody_told from schedule_outbox;

\echo == set up week three: one person has Friday off, one never works Wednesdays, one only asked for Tuesday off,
\echo == Saturday already has a shift, and Sunday is set by hand to nobody
insert into time_off (user_id, start_date, end_date, status) values
 (:'jaz', :'w3'::date + 4, :'w3'::date + 5, 'approved'),
 (:'mgr', :'w3'::date + 1, :'w3'::date + 1, 'pending');
insert into staff_availability (user_id, off_days) values (:'dee', '{3}');
set role authenticated;
insert into shifts (work_date, start_time, end_time, position, user_id) values (:'w3'::date + 5, '13:00', '17:00', 'Door', :'jaz');
select schedule_need_set(:'w3'::date + 6, 0, 'Closed');

\echo == filling week three: five shifts; Wednesday and one Friday night are left open, and it says whose they were and why
select schedule_usual_fill(:'w3') as r \gset
select case when (:'r'::jsonb ->> 'added')::int = 5 and jsonb_array_length(:'r'::jsonb -> 'open') = 2
             and (:'r'::jsonb -> 'open' -> 0 ->> 'user_id') = :'dee' and (:'r'::jsonb -> 'open' -> 0 ->> 'why') = 'never'
             and (:'r'::jsonb -> 'open' -> 0 ->> 'day')::date = :'w3'::date + 2
             and (:'r'::jsonb -> 'open' -> 1 ->> 'user_id') = :'jaz' and (:'r'::jsonb -> 'open' -> 1 ->> 'why') = 'off'
             and (:'r'::jsonb -> 'open' -> 1 ->> 'day')::date = :'w3'::date + 4
            then 'ok' else 'FAIL' end as left_open_with_why;
\echo == Saturday (already had a shift) and Sunday (closed by hand) are left alone
select case when (:'r'::jsonb -> 'days_kept') = to_jsonb(array[:'w3'::date + 5]) and (:'r'::jsonb -> 'days_closed') = to_jsonb(array[:'w3'::date + 6])
            then 'ok' else 'FAIL' end as kept_and_closed;
select case when count(*) filter (where work_date = :'w3'::date + 5) = 1 and count(*) filter (where work_date = :'w3'::date + 6) = 0
             and count(*) filter (where work_date = :'w3'::date + 2 and user_id is null) = 1
             and count(*) filter (where work_date = :'w3'::date + 4 and start_time = '17:30' and user_id is null) = 1
             and count(*) filter (where work_date = :'w3'::date + 4 and start_time = '17:30' and user_id = :'mgr') = 1
             and count(*) filter (where work_date = :'w3'::date + 4 and start_time = '12:30' and user_id = :'dee') = 1
            then 'ok' else 'FAIL' end as week_three_shifts
  from shifts where work_date between :'w3'::date and :'w3'::date + 6;
\echo == time off that is only asked for leaves the person on: Tuesday is still theirs
select case when count(*) = 1 then 'ok' else 'FAIL' end as asked_off_stays_on
  from shifts where work_date = :'w3'::date + 1 and user_id = :'mgr';

\echo == someone taken off the schedule: their usual shifts come out open, marked "gone"
select schedule_set_person(:'dee', 'Dee', false);
select schedule_usual_fill(:'w4') as r \gset
select case when (:'r'::jsonb ->> 'added')::int = 7 and jsonb_array_length(:'r'::jsonb -> 'open') = 3
             and (select count(*) from jsonb_array_elements(:'r'::jsonb -> 'open') o where o ->> 'user_id' = :'dee' and o ->> 'why' = 'gone') = 3
            then 'ok' else 'FAIL' end as off_the_schedule_is_open;
select case when count(*) = 0 then 'ok' else 'FAIL' end as none_left_on_them
  from shifts where work_date between :'w4'::date and :'w4'::date + 6 and user_id = :'dee';
select schedule_set_person(:'dee', 'Dee', true);

\echo == this week: days already gone are skipped, the rest are filled
reset role;
update staff_availability set off_days = '{}' where user_id = :'dee';
select count(*) filter (where :'w0'::date + ((weekday + 6) % 7) >= schedule_today()) as left_n,
       count(distinct weekday) filter (where :'w0'::date + ((weekday + 6) % 7) < schedule_today()) as past_days
  from usual_shifts where replaced_at is null \gset
set role authenticated;
select schedule_usual_fill(schedule_today()) as r \gset
select case when (:'r'::jsonb ->> 'added')::int = :left_n and jsonb_array_length(:'r'::jsonb -> 'days_past') = :past_days then 'ok' else 'FAIL' end as this_week_from_today;
select case when count(*) = 0 then 'ok' else 'FAIL' end as nothing_in_the_past from shifts where work_date < schedule_today();
\echo == a week that is over is refused (expect ERROR: That week is over)
select schedule_usual_fill(:'gone');

\echo == saving week three as the usual week: its six shifts, the open ones too; the old seven are kept, marked replaced
select case when schedule_usual_save(:'w3') = 6 then 'ok' else 'FAIL' end as saved_six;
select case when jsonb_array_length(schedule_usual()) = 6 then 'ok' else 'FAIL' end as usual_is_six;
reset role;
select case when count(*) filter (where replaced_at is null) = 6 and count(*) filter (where replaced_at is not null) = 7
             and count(*) filter (where replaced_at is null and saved_by is not null) = 6 then 'ok' else 'FAIL' end as old_week_kept
  from usual_shifts;
\echo == still nobody told about any shift: nothing was posted
select case when count(*) = 0 then 'ok' else 'FAIL' end as no_shift_notices from schedule_outbox where kind like 'shift%' or kind = 'published';
set role authenticated;

\echo == the new usual week fills a week with its own six
select schedule_usual_fill(:'w5') as r \gset
select case when (:'r'::jsonb ->> 'added')::int = 6 then 'ok' else 'FAIL' end as new_usual_fills;

\echo == a staff login may not see, fill or save the usual week (expect 3 ERRORs: Managers only)
select set_config('request.jwt.claim.sub', :'dee', false);
select schedule_usual();
select schedule_usual_fill(:'w5'::date + 7);
select schedule_usual_save(:'w2');
\echo == nor read or write the table behind it (expect 2 ERRORs: permission denied)
select * from usual_shifts;
insert into usual_shifts (weekday, start_time) values (1, '09:00');
\echo == the door login gets nothing either (expect ERROR: Managers only)
select set_config('request.jwt.claim.sub', :'door', false);
select schedule_usual();

\echo == the owner is a manager too
select set_config('request.jwt.claim.sub', :'sam', false);
select case when jsonb_array_length(schedule_usual()) = 6 then 'ok' else 'FAIL' end as owner_sees_it;
