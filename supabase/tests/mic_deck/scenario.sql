-- The open mic on the Stream Deck: mic_deck('load' | 'next' | 'skip').
-- Dates are built from today, so this runs the same any day. Every check line
-- should say ok. One step at the end is meant to be refused and prints ERROR.
\set ON_ERROR_STOP 0
create temp table t_ctx as select (now() at time zone 'America/Chicago')::date as today;
grant select on t_ctx to anon, authenticated;
create temp table t_r (step int primary key, r jsonb);
grant all on t_r to anon, authenticated;

-- No lineup tonight: the deck works the way it always has.
set role anon;
select case when mic_deck('load') = '{"on": false}'::jsonb then 'ok' else 'FAIL' end as "no lineup: off";
reset role;

-- Tonight, after the draw, in running order: three drawn names, a host pick, a drawn
-- name, a staff booking. One more signed up and wasn't drawn.
insert into mic_signups (mic_date, name, status, slot, host_pick)
  select today, v.name, v.status, v.slot, v.pick from t_ctx,
  (values ('Drawn A', 'drawn', 1, false), ('Drawn B', 'drawn', 2, false), ('Drawn C', 'drawn', 3, false),
          ('Pick', 'booked', 4, true), ('Drawn D', 'drawn', 5, false), ('Booked Last', 'booked', 6, false),
          ('Not Drawn', 'not_drawn', null, false)) v(name, status, slot, pick);
-- A lineup some other night doesn't count tonight.
insert into mic_signups (mic_date, name, status, slot) select today - 7, 'Last Week', 'drawn', 1 from t_ctx;

set role anon;
insert into t_r select 1, mic_deck('load');
select case when r->>'on' = 'true' and r->>'now' = '' and r->>'next' = 'Drawn A' and r->>'next_min' = '3'
             and r->>'n' = '0' and r->>'total' = '6' then 'ok' else 'FAIL ' || r::text end
  as "START SHOW: host is up, first comic next, 3 min" from t_r where step = 1;
select case when count(*) = 0 then 'ok' else 'FAIL' end as "START SHOW: nothing on the clock yet"
  from stage_timer where started_at is not null;

insert into t_r select 2, mic_deck('next');
select case when r->>'now' = 'Drawn A' and r->>'now_min' = '3' and r->>'next' = 'Drawn B' and r->>'n' = '1' and r->>'left' = '5'
             then 'ok' else 'FAIL ' || r::text end as "NEXT COMIC: first comic on" from t_r where step = 2;
select case when started_at is not null and set_seconds = 180 then 'ok' else 'FAIL' end
  as "NEXT COMIC: comic's clock started at 3 min" from stage_timer;

-- Drawn B isn't here: tap UP NEXT. They go to the end of the lineup.
insert into t_r select 3, mic_deck('skip');
select case when r->>'now' = 'Drawn A' and r->>'next' = 'Drawn C' and r->>'total' = '6' and r->>'n' = '1'
             then 'ok' else 'FAIL ' || r::text end as "skip: next one up, nobody on stage moved" from t_r where step = 3;

insert into t_r select 4, mic_deck('next');
insert into t_r select 5, mic_deck('load');  -- the deck restarted, START SHOW pressed again
select case when (select r from t_r where step = 5) = (select r from t_r where step = 4) then 'ok' else 'FAIL' end
  as "START SHOW again mid-show: picks up where it was";
select case when r->>'now' = 'Drawn C' and r->>'next' = 'Pick' and r->>'next_min' = '5' then 'ok' else 'FAIL ' || r::text end
  as "host pick shows 5 min" from t_r where step = 5;

insert into t_r select 6, mic_deck('next');
select case when set_seconds = 300 then 'ok' else 'FAIL' end as "host pick: clock at 5 min" from stage_timer;

-- Drawn D isn't here either; then staff add a late comic at the door.
insert into t_r select 7, mic_deck('skip');
select case when r->>'next' = 'Booked Last' and r->>'next_min' = '5' then 'ok' else 'FAIL ' || r::text end
  as "skip again: the booked comic is next" from t_r where step = 7;
reset role;
insert into mic_signups (mic_date, name, status, slot) select today, 'Late Add', 'booked', 9 from t_ctx;
set role anon;
insert into t_r select 8, mic_deck('next');
select case when r->>'now' = 'Booked Last' and r->>'next' = 'Drawn B' and r->>'total' = '7' and r->>'left' = '3'
             then 'ok' else 'FAIL ' || r::text end as "skipped comics come back at the end, late add after them" from t_r where step = 8;

-- Drawn B still isn't here: skipped a second time, they're off the lineup.
insert into t_r select 9, mic_deck('skip');
select case when r->>'next' = 'Drawn D' and r->>'total' = '6' then 'ok' else 'FAIL ' || r::text end
  as "skipped twice: off the lineup" from t_r where step = 9;

insert into t_r select 10, mic_deck('next');
select case when r->>'now' = 'Drawn D' and r->>'now_min' = '3' and r->>'next' = 'Late Add' and r->>'next_min' = '5'
             then 'ok' else 'FAIL ' || r::text end as "last comic shows 5 min" from t_r where step = 10;

-- The late add left before going up: cancelled, so nobody is next.
reset role;
update mic_signups set status = 'cancelled' where name = 'Late Add';
set role anon;
insert into t_r select 11, mic_deck('load');
select case when r->>'now' = 'Drawn D' and r->>'next' = '' and r->>'left' = '0' and r->>'total' = '5'
             then 'ok' else 'FAIL ' || r::text end as "cancelled comic drops out" from t_r where step = 11;

insert into t_r select 12, mic_deck('next');
select case when r->>'done' = 'true' and r->>'now' = '' and r->>'next' = '' then 'ok' else 'FAIL ' || r::text end
  as "after the last comic: lineup done" from t_r where step = 12;
select case when started_at is null then 'ok' else 'FAIL' end as "lineup done: comic's clock stopped" from stage_timer;
insert into t_r select 13, mic_deck('next');
insert into t_r select 14, mic_deck('load');
select case when (select r->>'done' from t_r where step = 13) = 'true' and (select r->>'done' from t_r where step = 14) = 'true'
            then 'ok' else 'FAIL' end as "done stays done, even after START SHOW again";

-- Skipping when nobody is left does nothing.
insert into t_r select 15, mic_deck('skip');
select case when r->>'done' = 'true' and r->>'total' = '5' then 'ok' else 'FAIL ' || r::text end
  as "skip with nobody left: nothing" from t_r where step = 15;

-- The website's logins can't read or change the deck's table directly.
select 'expect ERROR: anon reads the table';
select count(*) from mic_deck_runs;
select 'expect ERROR: unknown move';
select mic_deck('back');
reset role;
