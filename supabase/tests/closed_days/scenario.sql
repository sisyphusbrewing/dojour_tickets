\set ON_ERROR_STOP 0
\set sam '00000000-0000-0000-0000-000000000001'
\set mgr '00000000-0000-0000-0000-000000000002'
\set dee '00000000-0000-0000-0000-000000000003'
\set bld '00000000-0000-0000-0000-000000000004'
\set door '00000000-0000-0000-0000-000000000005'
-- Every check prints "ok" or "FAIL". Lines marked (expect ERROR) are meant to fail.
-- Test days are worked out from today, so this passes whatever day it is run.
select schedule_today() + 10 as d1, schedule_today() + 11 as d2, schedule_today() + 12 as d3 \gset
update staff_roles set builds_schedule = true where user_id = :'bld';

\echo == the holidays came with the file: Thanksgiving, Christmas Day and New Years Day, closed and needing nobody
select case when count(*) = 3 and bool_and(people = 0) then 'ok' else 'FAIL' end as holidays_closed
  from staffing_days where closed and day in ('2026-11-26', '2026-12-25', '2027-01-01');
select case when note = 'Closed for Christmas Day' then 'ok' else 'FAIL' end as christmas_note from staffing_days where day = '2026-12-25';
select case when note = 'Closed for New Year''s Day' then 'ok' else 'FAIL' end as new_years_note from staffing_days where day = '2027-01-01';

\echo == a plain staff login sees the closed day and why (but no numbers)
set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
select case when d ->> 'closed' = 'Closed for Christmas Day' and not (d ? 'people') then 'ok' else 'FAIL' end as staff_see_christmas
  from jsonb_array_elements(schedule_needs('2026-12-24', '2026-12-26') -> 'days') d where d ->> 'day' = '2026-12-25';
select case when d -> 'closed' = 'null'::jsonb then 'ok' else 'FAIL' end as christmas_eve_open
  from jsonb_array_elements(schedule_needs('2026-12-24', '2026-12-26') -> 'days') d where d ->> 'day' = '2026-12-24';
\echo (expect ERROR: Managers only, a plain staff login closing a day)
select schedule_day_close(:'d1', 'Closed');

\echo == the schedule builder marks a day closed; the number is nobody and the note says why
select set_config('request.jwt.claim.sub', :'bld', false);
select schedule_day_close(:'d1', 'Closed for a flood');
select case when (d ->> 'people')::int = 0 and d ->> 'closed' = 'Closed for a flood' and (d -> 'set' ->> 'closed')::boolean
            then 'ok' else 'FAIL' end as builder_closes
  from jsonb_array_elements(schedule_needs(:'d1', :'d1') -> 'days') d;
\echo == closed with no note says "Closed"
select schedule_day_close(:'d3', '');
select case when d ->> 'closed' = 'Closed' then 'ok' else 'FAIL' end as plain_closed
  from jsonb_array_elements(schedule_needs(:'d3', :'d3') -> 'days') d;

\echo (expect ERROR: closed, adding a shift to a closed day)
insert into shifts (work_date, start_time, end_time, position) values (:'d1', '16:00', '22:00', 'Bar');
insert into shifts (work_date, start_time, end_time, position, user_id, published) values (:'d2', '16:00', '22:00', 'Bar', :'dee', true);
\echo (expect ERROR: closed, moving a shift onto a closed day)
update shifts set work_date = :'d1' where work_date = :'d2';
\echo == changing a shift on an open day still works
update shifts set note = 'Two shows' where work_date = :'d2';
select case when count(*) = 1 then 'ok' else 'FAIL' end as open_day_ok from shifts where work_date = :'d2' and note = 'Two shows';
\echo (expect ERROR: Move or remove it first, closing a day that has a shift)
select schedule_day_close(:'d2', 'Closed');
reset role;
select case when not exists (select 1 from staffing_days where day = :'d2' and closed) then 'ok' else 'FAIL' end as not_closed_with_shift;
set role authenticated;

\echo == going back to the usual opens the day again, and a shift can go on it
select schedule_need_set(:'d1', null);
select case when d -> 'closed' = 'null'::jsonb and d -> 'set' = 'null'::jsonb then 'ok' else 'FAIL' end as reopened
  from jsonb_array_elements(schedule_needs(:'d1', :'d1') -> 'days') d;
insert into shifts (work_date, start_time, end_time, position) values (:'d1', '16:00', '22:00', 'Bar');
select case when count(*) = 1 then 'ok' else 'FAIL' end as shift_after_reopen from shifts where work_date = :'d1';
\echo == a number set by hand without "closed" is not a closed day
select schedule_need_set(:'d3', 0, 'Quiet night');
select case when d -> 'closed' = 'null'::jsonb and (d ->> 'people')::int = 0 then 'ok' else 'FAIL' end as zero_is_not_closed
  from jsonb_array_elements(schedule_needs(:'d3', :'d3') -> 'days') d;

\echo == the phone calendar carries the closed days as all-day days, with the shifts
select schedule_day_close(:'d3', 'Closed for a party');
select set_config('request.jwt.claim.sub', :'dee', false);
select my_calendar_feed() as tok \gset
reset role; set role service_role;
select schedule_calendar(:'tok') as cal \gset
reset role;
select case when jsonb_array_length((:'cal')::jsonb -> 'shifts') = 1 then 'ok' else 'FAIL' end as calendar_shift;
select case when c ->> 'next' = to_char(:'d3'::date + 1, 'YYYYMMDD') and c ->> 'note' = 'Closed for a party' then 'ok' else 'FAIL' end as calendar_closed_day
  from jsonb_array_elements((:'cal')::jsonb -> 'closed') c where c ->> 'day' = to_char(:'d3'::date, 'YYYYMMDD');
select case when exists (select 1 from jsonb_array_elements((:'cal')::jsonb -> 'closed') c
                          where c ->> 'day' = '20261225' and c ->> 'note' = 'Closed for Christmas Day')
             or '2026-12-25'::date > schedule_today() + 366 or '2026-12-25'::date < schedule_today() - 60
            then 'ok' else 'FAIL' end as calendar_christmas;
