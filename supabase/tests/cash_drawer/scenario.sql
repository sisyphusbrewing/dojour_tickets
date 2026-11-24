\set ON_ERROR_STOP 0
\set sam '00000000-0000-0000-0000-000000000001'
\set mgr '00000000-0000-0000-0000-000000000002'
\set dee '00000000-0000-0000-0000-000000000003'
\set jay '00000000-0000-0000-0000-000000000004'
\set door '00000000-0000-0000-0000-000000000005'
-- Every check prints "ok" or "FAIL". Lines marked (expect ERROR) are meant to fail.
reset role;
update staff_roles set on_schedule = true where user_id in (:'dee', :'jay');

\echo == the door login cannot see or count the drawer (expect 2 ERRORs: Staff only)
set role authenticated; select set_config('request.jwt.claim.sub', :'door', false);
select cash_status();
select cash_count_save('open', '{"20":15}'::jsonb, 0, '');

\echo == nobody has counted today: the opening count is due, and it starts at 300
select set_config('request.jwt.claim.sub', :'jay', false);
select case when (cash_status() ->> 'open_due')::boolean and (cash_status() ->> 'start')::numeric = 300 then 'ok' else 'FAIL' end as open_due;

\echo == Jay clocks in and counts: 10 twenties, 15 fives, 25 ones and 0.00 in coins = 300
select case when (clock_punch(null) ->> 'did') = 'in' then 'ok' else 'FAIL' end as jay_in;
select case when (cash_count_save('open', '{"20":10,"5":15,"1":25}'::jsonb, 0, '') -> 'open' ->> 'total')::numeric = 300 then 'ok' else 'FAIL' end as open_300;
select case when not (cash_status() ->> 'open_due')::boolean then 'ok' else 'FAIL' end as open_done;
select case when (cash_status() -> 'open' ->> 'by') is not null then 'ok' else 'FAIL' end as says_who;

\echo == bad counts are refused (expect 5 ERRORs)
select cash_count_save('middle', '{"20":1}'::jsonb, 0, '');
select cash_count_save('close', '{"3":1}'::jsonb, 0, '');
select cash_count_save('close', '{"20":-1}'::jsonb, 0, '');
select cash_count_save('close', '{"20":1.5}'::jsonb, 0, '');
select cash_count_save('close', '{"20":1}'::jsonb, 1.234, '');

\echo == staff cannot write counts straight or see the manager list (expect 2 ERRORs: permission denied, Managers only)
insert into cash_counts (cash_day, kind, counted_by, total) values (cash_day(), 'open', :'jay', 1);
select case when count(*) = 0 then 'ok' else 'FAIL' end as staff_sees_no_rows from cash_counts;
select cash_days(cash_day() - 7, cash_day());

\echo == Dee clocks in too: while Dee is on, Jay is not the last one, so no close count is due for Jay
select set_config('request.jwt.claim.sub', :'dee', false);
select case when (clock_punch(null) ->> 'did') = 'in' then 'ok' else 'FAIL' end as dee_in;
select set_config('request.jwt.claim.sub', :'jay', false);
select case when not (cash_status() ->> 'close_due')::boolean and (cash_status() ->> 'others_on')::int = 1 then 'ok' else 'FAIL' end as jay_not_last;

\echo == Dee clocks out (3 hours later); now Jay is the last one and the close count is due
reset role;
update time_punches set clock_in = now() - interval '3 hours' where clock_out is null;
set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
select case when (clock_punch(null) ->> 'did') = 'out' then 'ok' else 'FAIL' end as dee_out;
select set_config('request.jwt.claim.sub', :'jay', false);
select case when (cash_status() ->> 'close_due')::boolean then 'ok' else 'FAIL' end as jay_is_last;

\echo == Jay counts at close: 300 + 142.50 = 442.50; then a recount of 445.25 replaces it
select case when (cash_count_save('close', '{"100":1,"50":2,"20":9,"10":4,"5":4,"1":2}'::jsonb, 0.50, '') -> 'close' ->> 'total')::numeric = 442.50 then 'ok' else 'FAIL' end as close_442_50;
select case when (cash_count_save('close', '{"100":1,"50":2,"20":9,"10":4,"5":4,"1":5}'::jsonb, 0.25, 'found 3 ones under the tray') -> 'close' ->> 'total')::numeric = 445.25 then 'ok' else 'FAIL' end as recount;
select case when not (cash_status() ->> 'close_due')::boolean then 'ok' else 'FAIL' end as close_done;

\echo == counts can never be changed or deleted, not even by the database owner (expect 2 ERRORs: never changed)
reset role;
update cash_counts set total = 0;
delete from cash_counts;

\echo == Claude writes what GoTab took (service key): 140.00
insert into cash_gotab (cash_day, gotab_cash) values (cash_day(), 140.00);

\echo == the manager sees the day: 300 in, 445.25 out, 145.25 came in, GoTab 140, 5.25 over, 3 counts
set role authenticated; select set_config('request.jwt.claim.sub', :'mgr', false);
select case when open_total = 300 and close_total = 445.25 and came_in = 145.25 and gotab_cash = 140 and difference = 5.25 and counts = 3
            then 'ok' else 'FAIL' end as manager_view
  from cash_days(cash_day() - 7, cash_day()) where cash_day = cash_day();
select case when count(*) = 3 then 'ok' else 'FAIL' end as manager_reads_rows from cash_counts;

\echo == a day with only the GoTab number still shows, with the counts missing
reset role;
insert into cash_gotab (cash_day, gotab_cash) values (cash_day() - 1, 20);
set role authenticated; select set_config('request.jwt.claim.sub', :'mgr', false);
select case when open_total is null and close_total is null and difference is null and gotab_cash = 20 then 'ok' else 'FAIL' end as missing_counts
  from cash_days(cash_day() - 7, cash_day()) where cash_day = cash_day() - 1;

\echo == a 1:30 AM count belongs to the night before
reset role;
select case when ((timestamptz '2026-11-25 01:30:00 America/Chicago' at time zone 'America/Chicago') - interval '5 hours')::date = date '2026-11-24' then 'ok' else 'FAIL' end as late_close_day;
