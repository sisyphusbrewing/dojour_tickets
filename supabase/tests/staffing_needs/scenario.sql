\set ON_ERROR_STOP 0
\set sam '00000000-0000-0000-0000-000000000001'
\set mgr '00000000-0000-0000-0000-000000000002'
\set dee '00000000-0000-0000-0000-000000000003'
\set door '00000000-0000-0000-0000-000000000005'
-- Every check prints "ok" or "FAIL". Lines marked (expect ERROR) are meant to fail.
-- Days are worked out from today, so this passes whatever day it is run:
-- each is the first Monday, Tuesday, ... that is at least a week away.
select schedule_today() + 7 + ((1 - extract(dow from schedule_today() + 7)::int + 7) % 7) as mon,
       schedule_today() + 7 + ((2 - extract(dow from schedule_today() + 7)::int + 7) % 7) as tue,
       schedule_today() + 7 + ((3 - extract(dow from schedule_today() + 7)::int + 7) % 7) as wed,
       schedule_today() + 7 + ((4 - extract(dow from schedule_today() + 7)::int + 7) % 7) as thu,
       schedule_today() + 7 + ((5 - extract(dow from schedule_today() + 7)::int + 7) % 7) as fri,
       schedule_today() + 7 + ((6 - extract(dow from schedule_today() + 7)::int + 7) % 7) as sat,
       schedule_today() + 7 + ((0 - extract(dow from schedule_today() + 7)::int + 7) % 7) as sun,
       schedule_today() + 21 + ((4 - extract(dow from schedule_today() + 21)::int + 7) % 7) as thu2,
       schedule_today() + 21 + ((1 - extract(dow from schedule_today() + 21)::int + 7) % 7) as mon2,
       schedule_today() + 21 + ((6 - extract(dow from schedule_today() + 21)::int + 7) % 7) as sat2,
       schedule_today() + 21 + ((0 - extract(dow from schedule_today() + 21)::int + 7) % 7) as sun2 \gset

\echo == set up: Thanksgiving 2026 came with the rules as a day set by hand
select case when people = 0 and note = 'Closed for Thanksgiving' then 'ok' else 'FAIL' end as thanksgiving_closed
  from staffing_days where day = '2026-11-26';
-- Put back to the rules here so it can't land on one of the test days.
update staffing_days set people = null;

\echo == set up: the calendar
-- Friday: a ticketed show at 7 and 9, each with a General and a Premium row (one showtime, not two).
insert into exchange_showtimes (variant_id, show_title, date_text, ticket_type, starts_at, price) values
 (1, 'The Dose', 'FRI 7', 'General Admission', (:'fri'::date + time '19:00') at time zone 'America/Chicago', 28),
 (2, 'The Dose', 'FRI 7', 'Premium Seating',   (:'fri'::date + time '19:00') at time zone 'America/Chicago', 38),
 (3, 'The Dose', 'FRI 9', 'General Admission', (:'fri'::date + time '21:00') at time zone 'America/Chicago', 28),
 -- Thursday: the free showcase at 8.
 (4, 'Thursday Showcase', 'THU 8', 'General Admission', (:'thu'::date + time '20:00') at time zone 'America/Chicago', 0),
 -- The Thursday two weeks on: a ticketed show at 7 and the free showcase at 8.
 (5, 'Peyton Ruddy', 'THU2 7', 'General Admission', (:'thu2'::date + time '19:00') at time zone 'America/Chicago', 28),
 (6, 'Thursday Showcase', 'THU2 8', 'General Admission', (:'thu2'::date + time '20:00') at time zone 'America/Chicago', 0),
 -- Sunday: a 6 PM show, the hour the taproom closes.
 (7, 'Sunday Special', 'SUN 6', 'General Admission', (:'sun'::date + time '18:00') at time zone 'America/Chicago', 20),
 -- A Monday (closed) with a show, and a cancelled show on the Saturday.
 (8, 'Monday Taping', 'MON2 7', 'General Admission', (:'mon2'::date + time '19:00') at time zone 'America/Chicago', 15),
 (9, 'CANCELLED: Nobody', 'SAT 7', 'General Admission', (:'sat'::date + time '19:00') at time zone 'America/Chicago', 25),
 -- Early ones: a 5 PM Sunday show, a free event at 6 on a Wednesday, and a
 -- Saturday show at 6:30, which is not early.
 (10, 'Lobby Show', 'SUN2 5', 'General Admission', (:'sun2'::date + time '17:00') at time zone 'America/Chicago', 20),
 (11, 'Early Trivia', 'WED 6', 'General Admission', (:'wed'::date + time '18:00') at time zone 'America/Chicago', 0),
 (12, 'Half Past', 'SAT2 630', 'General Admission', (:'sat2'::date + time '18:30') at time zone 'America/Chicago', 22);
-- Tickets for Friday at 7: 40 on the website, 10 on Dojour, plus the venue's
-- own Dojour hold (no email) and 5 comps, which are not sales.
insert into tickets (show_title, show_date, tickets, source, email) values
 ('The Dose', 'FRI 7', 40, 'Website', 'a@example.com'), ('The Dose ', 'FRI 7', 10, 'Dojour', 'b@example.com'),
 ('The Dose', 'FRI 7', 30, 'Dojour', ''), ('The Dose', 'FRI 7', 5, 'Comp', 'c@example.com'),
 ('The Dose', 'FRI 9', 12, 'Website', 'd@example.com');

set role authenticated; select set_config('request.jwt.claim.sub', :'mgr', false);
-- One day of what a manager is told.
create or replace function pg_temp.day(p date) returns jsonb language sql as $$ select schedule_needs(p, p) -> 'days' -> 0 $$;

\echo == a plain Tuesday (open 4 to 9): one person
select case when (pg_temp.day(:'tue') ->> 'people')::int = 1 and jsonb_array_length(pg_temp.day(:'tue') -> 'parts') = 1
             and (pg_temp.day(:'tue') -> 'parts' -> 0 ->> 'why') = 'open' and not (pg_temp.day(:'tue') -> 'parts' -> 0 ->> 'split')::boolean
            then 'ok' else 'FAIL' end as tuesday_one;
\echo == a plain Saturday (open 1 to 11): two, an opener and a closer. The cancelled show is not counted.
select case when (pg_temp.day(:'sat') ->> 'people')::int = 2 and (pg_temp.day(:'sat') -> 'parts' -> 0 ->> 'split')::boolean
             and jsonb_array_length(pg_temp.day(:'sat') -> 'events') = 0 then 'ok' else 'FAIL' end as saturday_two;
\echo == Friday with a ticketed show at 7 and 9: three, the third from 5:30
select case when (pg_temp.day(:'fri') ->> 'people')::int = 3 and (pg_temp.day(:'fri') -> 'parts' -> 1 ->> 'why') = 'show'
             and (pg_temp.day(:'fri') -> 'parts' -> 1 ->> 'from')::int = 17 * 60 + 30
             and (pg_temp.day(:'fri') -> 'parts' -> 1 ->> 'title') = 'The Dose' then 'ok' else 'FAIL' end as friday_three;
\echo == its two showtimes are listed once each, with tickets sold (website + Dojour, no holds, no comps)
select case when jsonb_array_length(pg_temp.day(:'fri') -> 'events') = 2
             and (pg_temp.day(:'fri') -> 'events' -> 0 ->> 'sold')::int = 50 and (pg_temp.day(:'fri') -> 'events' -> 0 ->> 'time') = '7:00 PM'
             and (pg_temp.day(:'fri') -> 'events' -> 1 ->> 'sold')::int = 12 and not (pg_temp.day(:'fri') -> 'events' -> 0 ->> 'free')::boolean
            then 'ok' else 'FAIL' end as friday_events;
\echo == Thursday with the free showcase at 8: two, the second from 6:30
select case when (pg_temp.day(:'thu') ->> 'people')::int = 2 and (pg_temp.day(:'thu') -> 'parts' -> 1 ->> 'why') = 'free'
             and (pg_temp.day(:'thu') -> 'parts' -> 1 ->> 'from')::int = 18 * 60 + 30
             and (pg_temp.day(:'thu') -> 'events' -> 0 ->> 'free')::boolean then 'ok' else 'FAIL' end as thursday_two;
\echo == a Thursday with a ticketed show AND the free showcase: still two, not three
select case when (pg_temp.day(:'thu2') ->> 'people')::int = 2 and jsonb_array_length(pg_temp.day(:'thu2') -> 'parts') = 2
             and (pg_temp.day(:'thu2') -> 'parts' -> 1 ->> 'why') = 'show' then 'ok' else 'FAIL' end as both_is_two;
\echo == Sunday (open 1 to 6) with a 6 PM show: two, and the day runs to 8
select case when (pg_temp.day(:'sun') ->> 'people')::int = 2 and (pg_temp.day(:'sun') -> 'parts' -> 0 ->> 'to')::int = 20 * 60
             and not (pg_temp.day(:'sun') -> 'parts' -> 0 ->> 'split')::boolean then 'ok' else 'FAIL' end as sunday_show;
\echo == its extra person starts at 5:00, an hour before, not 4:30 (Sam, Nov 17 2026: a 6pm show, shifts start at 5pm)
select case when (pg_temp.day(:'sun') -> 'parts' -> 1 ->> 'why') = 'show'
             and (pg_temp.day(:'sun') -> 'parts' -> 1 ->> 'from')::int = 17 * 60 then 'ok' else 'FAIL' end as six_pm_show_from_five;
\echo == a 5 PM show: from 4:00, and the day runs to 7
select case when (pg_temp.day(:'sun2') ->> 'people')::int = 2 and (pg_temp.day(:'sun2') -> 'parts' -> 1 ->> 'from')::int = 16 * 60
             and (pg_temp.day(:'sun2') -> 'parts' -> 0 ->> 'to')::int = 19 * 60 then 'ok' else 'FAIL' end as five_pm_show_from_four;
\echo == a free event at 6 PM gets the same hour: from 5:00
select case when (pg_temp.day(:'wed') ->> 'people')::int = 2 and (pg_temp.day(:'wed') -> 'parts' -> 1 ->> 'why') = 'free'
             and (pg_temp.day(:'wed') -> 'parts' -> 1 ->> 'from')::int = 17 * 60 then 'ok' else 'FAIL' end as free_at_six_from_five;
\echo == a 6:30 show is not an early one: 90 minutes before, which is also 5:00
select case when (pg_temp.day(:'sat2') ->> 'people')::int = 3 and (pg_temp.day(:'sat2') -> 'parts' -> 1 ->> 'from')::int = 17 * 60
            then 'ok' else 'FAIL' end as half_past_six_is_ninety;
\echo == the page is told the two early numbers along with the rest
select case when (r ->> 'early_at')::int = 18 * 60 and (r ->> 'early_lead')::int = 60 and (r ->> 'lead_minutes')::int = 90
             and not (r ? 'hours') and not (r ? 'id') then 'ok' else 'FAIL' end as early_numbers_sent
  from (select schedule_needs(:'mon', :'mon') -> 'rules' as r) q;
\echo == Monday is closed: nobody. A show on a Monday: one to run the bar and one more.
select case when (pg_temp.day(:'mon') ->> 'people')::int = 0 and jsonb_array_length(pg_temp.day(:'mon') -> 'parts') = 0
             and (pg_temp.day(:'mon') -> 'open') = 'null'::jsonb then 'ok' else 'FAIL' end as monday_closed;
select case when (pg_temp.day(:'mon2') ->> 'people')::int = 2 and (pg_temp.day(:'mon2') -> 'parts' -> 0 ->> 'why') = 'closed'
            then 'ok' else 'FAIL' end as monday_show;
\echo == a day already gone gets no number
select case when not (pg_temp.day(schedule_today() - 1) ? 'people') then 'ok' else 'FAIL' end as past_no_number;
\echo == a whole week comes back as seven days, with the rules for a manager
select case when jsonb_array_length(schedule_needs(:'mon', :'mon'::date + 6) -> 'days') = 7
             and (schedule_needs(:'mon', :'mon'::date + 6) -> 'rules' ->> 'open_people')::int = 1 then 'ok' else 'FAIL' end as a_week;

\echo == the manager says a show with 50 or more sold needs one more again: Friday is four
select schedule_needs_rules(1, 1, 1, 1, 50, 90);
select case when (pg_temp.day(:'fri') ->> 'people')::int = 4 and (pg_temp.day(:'fri') -> 'parts' -> 1 ->> 'full')::boolean
             and (pg_temp.day(:'fri') -> 'parts' -> 1 ->> 'people')::int = 2 then 'ok' else 'FAIL' end as full_room;
\echo == two on at a time and two hours of lead: Friday is 2x2 + 2, from 5:00
select schedule_needs_rules(2, 1, 1, 1, 50, 120);
select case when (pg_temp.day(:'fri') ->> 'people')::int = 6 and (pg_temp.day(:'fri') -> 'parts' -> 1 ->> 'from')::int = 17 * 60
            then 'ok' else 'FAIL' end as bigger_numbers;
\echo == ...but the 6 PM show keeps its hour: still 5:00
select case when (pg_temp.day(:'sun') -> 'parts' -> 1 ->> 'from')::int = 17 * 60 then 'ok' else 'FAIL' end as early_show_keeps_its_hour;
\echo == a number out of range is refused (expect ERROR: out of range)
select schedule_needs_rules(1, 1, 1, 1, 0, 90);
\echo == back to the starting numbers
select schedule_needs_rules(1, 1, 1, 0, 60, 90);
select case when (pg_temp.day(:'fri') ->> 'people')::int = 3 then 'ok' else 'FAIL' end as back_to_three;

\echo == the manager sets Friday by hand (a private party): five, with the note, and what the rules said is kept
select schedule_need_set(:'fri', 5, 'Private party in the back room');
select case when (pg_temp.day(:'fri') ->> 'people')::int = 5 and (pg_temp.day(:'fri') ->> 'rule_people')::int = 3
             and (pg_temp.day(:'fri') -> 'set' ->> 'note') = 'Private party in the back room' then 'ok' else 'FAIL' end as set_by_hand;
\echo == closed for a holiday: zero by hand
select schedule_need_set(:'tue', 0, 'Closed');
select case when (pg_temp.day(:'tue') ->> 'people')::int = 0 and (pg_temp.day(:'tue') ->> 'rule_people')::int = 1 then 'ok' else 'FAIL' end as closed_by_hand;
\echo == an empty number goes back to the rules
select schedule_need_set(:'fri', null);
select case when (pg_temp.day(:'fri') ->> 'people')::int = 3 and (pg_temp.day(:'fri') -> 'set') = 'null'::jsonb then 'ok' else 'FAIL' end as back_to_rules;
\echo == a silly number for one day is refused (expect ERROR: out of range)
select schedule_need_set(:'fri', 41, 'no');
\echo == more than two months at once is refused (expect ERROR: two months or less)
select schedule_needs(:'mon', :'mon'::date + 90);

\echo == a staff login sees the events but no numbers and no rules
select set_config('request.jwt.claim.sub', :'dee', false);
select case when jsonb_array_length(pg_temp.day(:'fri') -> 'events') = 2 and not (pg_temp.day(:'fri') ? 'people')
             and (schedule_needs(:'fri', :'fri') -> 'rules') = 'null'::jsonb then 'ok' else 'FAIL' end as staff_see_events_only;
\echo == a staff login cannot change the numbers or set a day (expect 2 ERRORs: Managers only)
select schedule_needs_rules(0, 0, 0, 0, 60, 90);
select schedule_need_set(:'fri', 0, 'nope');
\echo == nor read or write the tables behind them (expect 3 ERRORs: permission denied)
select * from staffing_settings;
select * from staffing_days;
update staffing_settings set open_people = 0;
\echo == the door login gets nothing (expect ERROR: Staff only)
select set_config('request.jwt.claim.sub', :'door', false);
select schedule_needs(:'fri', :'fri');

\echo == the owner is a manager too
select set_config('request.jwt.claim.sub', :'sam', false);
select case when (pg_temp.day(:'fri') ->> 'people')::int = 3 then 'ok' else 'FAIL' end as owner_sees_numbers;
