\set ON_ERROR_STOP 0
\set mgr '00000000-0000-0000-0000-000000000002'
\set dee '00000000-0000-0000-0000-000000000003'
-- Every check prints "ok" or "FAIL". Lines marked (expect ERROR) are meant to fail.
-- Test days are 40 to 42 days out (clear of the real closed holidays nearby), worked out from today.
select schedule_today() as today, schedule_today() + 40 as d1, schedule_today() + 41 as d2, schedule_today() + 42 as d3 \gset
create or replace function pg_temp.day(p date) returns jsonb language sql as $$
  select d from jsonb_array_elements(schedule_needs(p, p) -> 'days') d $$;

\echo == title words: short words and common ones do not count
select case when cal_words('Tuesday Open Mic @ 7PM') = '{open}' and cal_words('Ben Katzner (Day 1/2)') @> '{katzner}'
             and cal_words('Private party') = '{}' then 'ok' else 'FAIL' end as words;

\echo == set up: a website show on d1 and the calendar holding it, a private party, an all-day rental
insert into exchange_showtimes (variant_id, show_title, date_text, ticket_type, starts_at, price) values
 (901, 'Ben Katzner', 'D1 7', 'General Admission', (:'d1'::date + time '19:00') at time zone 'America/Chicago', 25);
set role service_role;
select venue_calendar_save(:'today', jsonb_build_array(
  jsonb_build_object('uid', 'a', 'day', :'d1', 'title', 'Ben Katzner (Day 1/2)', 'all_day', true),
  jsonb_build_object('uid', 'b', 'day', :'d1', 'title', 'Sip and Sitch', 'all_day', false,
                     'starts_at', (:'d1'::date + time '13:00') at time zone 'America/Chicago',
                     'ends_at', (:'d1'::date + time '15:00') at time zone 'America/Chicago'),
  jsonb_build_object('uid', 'c', 'day', :'d2', 'title', 'Josh Light Wedding Rental', 'all_day', true),
  jsonb_build_object('uid', 'd', 'day', :'d3', 'title', 'Old party', 'all_day', true))) as saved \gset
reset role;
select case when (:'saved')::jsonb ->> 'kept' = '4' then 'ok' else 'FAIL' end as saved_four;

set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
\echo == staff see the private party with its time, not a second Ben Katzner
select case when (select count(*) from jsonb_array_elements(pg_temp.day(:'d1') -> 'events') e where e ->> 'title' like 'Ben Katzner%') = 1
             and exists (select 1 from jsonb_array_elements(pg_temp.day(:'d1') -> 'events') e
                          where e ->> 'title' = 'Sip and Sitch' and e ->> 'time' = '1:00 PM' and (e ->> 'cal')::boolean)
            then 'ok' else 'FAIL' end as staff_see_party;
\echo == an all-day rental shows with no time
select case when exists (select 1 from jsonb_array_elements(pg_temp.day(:'d2') -> 'events') e
                          where e ->> 'title' = 'Josh Light Wedding Rental' and e -> 'time' = 'null'::jsonb and (e ->> 'all_day')::boolean)
            then 'ok' else 'FAIL' end as staff_see_rental;
\echo (expect ERROR: permission denied, staff reading the calendar table)
select * from venue_calendar;
\echo (expect ERROR: permission denied, staff saving the calendar)
select venue_calendar_save(:'today', '[{"uid":"x","day":"2030-01-01","title":"x"}]');

select set_config('request.jwt.claim.sub', :'mgr', false);
\echo == the private party counts like a free event: one more person, from an hour before (1 PM is an early start)
select case when exists (select 1 from jsonb_array_elements(pg_temp.day(:'d1') -> 'parts') p where p ->> 'why' in ('show', 'free'))
            then 'ok' else 'FAIL' end as party_in_parts;
select case when (pg_temp.day(:'d2') ->> 'people')::int = (pg_temp.day(:'d2') ->> 'rule_people')::int
             and not exists (select 1 from jsonb_array_elements(pg_temp.day(:'d2') -> 'parts') p where p ->> 'why' = 'free')
            then 'ok' else 'FAIL' end as rental_no_extra;
reset role;

\echo == a second save without the old party marks it gone; it leaves the Schedule
set role service_role;
select venue_calendar_save(:'today', jsonb_build_array(
  jsonb_build_object('uid', 'a', 'day', :'d1', 'title', 'Ben Katzner (Day 1/2)', 'all_day', true),
  jsonb_build_object('uid', 'b', 'day', :'d1', 'title', 'Sip and Sitch', 'all_day', false,
                     'starts_at', (:'d1'::date + time '13:00') at time zone 'America/Chicago'),
  jsonb_build_object('uid', 'c', 'day', :'d2', 'title', 'Josh Light Wedding Rental', 'all_day', true))) as saved2 \gset
\echo (expect ERROR: Nothing to save, an empty read never wipes the calendar)
select venue_calendar_save(:'today', '[]');
reset role;
select case when (:'saved2')::jsonb ->> 'gone' = '1' and (select gone from venue_calendar where uid = 'd')
             and (select count(*) from venue_calendar) = 4 then 'ok' else 'FAIL' end as gone_not_deleted;
set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
select case when jsonb_array_length(pg_temp.day(:'d3') -> 'events') = 0 then 'ok' else 'FAIL' end as gone_off_schedule;

\echo == a shift on the phone calendar says what else is on that day
reset role;
insert into shifts (work_date, start_time, end_time, position, user_id, published) values (:'d1', '12:00', '18:00', 'Bar', :'dee', true);
set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
select my_calendar_feed() as tok \gset
reset role; set role service_role;
select case when s -> 'events' = '["Sip and Sitch, 1:00 PM"]'::jsonb then 'ok' else 'FAIL' end as shift_lists_party
  from jsonb_array_elements(schedule_calendar(:'tok') -> 'shifts') s;
reset role;
