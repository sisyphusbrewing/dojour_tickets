-- Checks for printed comic checks (20261119060000_comic_checks.sql).
-- Each check prints ok or FAIL. Steps that are meant to be refused say how
-- many ERRORs to expect just above them.
\set ON_ERROR_STOP 0
set role authenticated;

-- Grace (manager) drafts a check for Nate's line.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
create temp table d as select check_draft('20000000-0000-0000-0000-000000000001') v;
grant all on d to public;
select case when v->>'status' = 'draft' and v->>'number' is null and v->>'pay_to' = 'Nathan Varrone' and (v->>'amount')::numeric = 1920
  then 'ok' else 'FAIL' end || ' manager drafts a check to the legal name, no number yet' from d;
select case when (check_draft('20000000-0000-0000-0000-000000000001'))->>'id' = (select v->>'id' from d)
  then 'ok' else 'FAIL' end || ' asking twice gives the same draft';
\echo 'expect 3 ERRORs: a manager cannot approve, write the table, or delete'
select check_approve((select (v->>'id')::uuid from d));
update checks set status = 'approved' where id = (select (v->>'id')::uuid from d);
delete from checks;

-- Darrin (staff) can't draft or see checks.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000003', false);
\echo 'expect 1 ERROR: staff cannot draft'
select check_draft('20000000-0000-0000-0000-000000000002');
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' staff see no checks' from checks;

-- The PC finds nothing to print before Sam's OK, and a wrong code gets nothing.
reset role; set role anon;
select set_config('request.jwt.claim.sub', '', false);
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' nothing prints before approval' from checks_to_print('office-pc', 'pc-secret');
\echo 'expect 1 ERROR: wrong code'
select * from checks_to_print('office-pc', 'guess');

-- The service key (what GitHub holds) can't approve or skip ahead either.
reset role; set role service_role;
\echo 'expect 4 ERRORs: the service key cannot approve, number, insert an approved check, or call approve'
update checks set status = 'approved' where id = (select (v->>'id')::uuid from d);
update checks set status = 'printing', number = 5, approved_at = now() where id = (select (v->>'id')::uuid from d);
insert into checks (pay_to, amount, status, number) values ('Mallory', 9999, 'approved', 7);
select case when check_approve((select (v->>'id')::uuid from d)) is null then 'FAIL' else 'FAIL' end || ' (service key approve should have errored)';

-- Sam sets the first number and approves.
reset role; set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
select case when check_first_number(5001) = 5001 then 'ok' else 'FAIL' end || ' owner sets the first number';
select case when (x->>'number')::int = 5001 and x->>'status' = 'approved' and x->>'approved_by' = 'ticketing@sisyphusbrewing.com'
  then 'ok' else 'FAIL' end || ' owner approves, number 5001'
  from (select check_approve((select (v->>'id')::uuid from d)) x) y;
\echo 'expect 3 ERRORs: approve twice, change the amount, set the first number again'
select check_approve((select (v->>'id')::uuid from d));
update checks set amount = 19200 where id = (select (v->>'id')::uuid from d);
select check_first_number(1);

-- The PC picks it up once.
reset role; set role anon;
select set_config('request.jwt.claim.sub', '', false);
create temp table pr as select x from checks_to_print('office-pc', 'pc-secret') x;
select case when count(*) = 1 and min((x->>'number')::int) = 5001 and min(x->>'pay_to') = 'Nathan Varrone'
  then 'ok' else 'FAIL' end || ' PC gets check 5001' from pr;
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' it is not handed out twice' from checks_to_print('office-pc', 'pc-secret');
select case when check_printed('office-pc', 'pc-secret', (select (v->>'id')::uuid from d), true, 'Brother') then 'ok' else 'FAIL' end || ' PC says printed';
select case when not check_printed('office-pc', 'pc-secret', (select (v->>'id')::uuid from d), true) then 'ok' else 'FAIL' end || ' saying it twice does nothing';
reset role;
select case when status = 'paid' and paid_via = 'Check #5001' then 'ok' else 'FAIL' end || ' the pay line is marked paid by check 5001'
  from payouts where id = '20000000-0000-0000-0000-000000000001';

-- Aiden: no legal name, so his stage name. Draft by Sam, approve, then the printer fails.
set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
create temp table a as select check_draft('20000000-0000-0000-0000-000000000002') v;
grant all on a to public;
select case when (check_approve((select (v->>'id')::uuid from a)))->>'number' = '5002' then 'ok' else 'FAIL' end || ' next check is 5002';
reset role; set role anon;
select set_config('request.jwt.claim.sub', '', false);
select count(*) from checks_to_print('office-pc', 'pc-secret');
select case when check_printed('office-pc', 'pc-secret', (select (v->>'id')::uuid from a), false, 'Out of paper') then 'ok' else 'FAIL' end || ' PC says it failed';
reset role; set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
\echo 'expect 2 ERRORs: a manager cannot retry or void a check that went to the printer'
select check_retry((select (v->>'id')::uuid from a));
select check_void((select (v->>'id')::uuid from a), 'jammed');
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
select case when (check_retry((select (v->>'id')::uuid from a)))->>'status' = 'approved' then 'ok' else 'FAIL' end || ' owner sends it again, same number';
\echo 'expect 1 ERROR: a void needs a reason'
select check_void((select (v->>'id')::uuid from a), ' ');
select case when (check_void((select (v->>'id')::uuid from a), 'Wrong amount'))->>'status' = 'void' then 'ok' else 'FAIL' end || ' owner voids it';
reset role; set role anon;
select set_config('request.jwt.claim.sub', '', false);
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' a voided check never prints' from checks_to_print('office-pc', 'pc-secret');

-- Voiding the printed 5001 puts Nate's line back to owed; a new draft gets 5003.
reset role; set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
select check_void((select (v->>'id')::uuid from d), 'Lost in the mail');
reset role;
select case when status = 'owed' and paid_via is null then 'ok' else 'FAIL' end || ' voiding a printed check puts the line back to owed'
  from payouts where id = '20000000-0000-0000-0000-000000000001';
set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
select case when (check_approve(((check_draft('20000000-0000-0000-0000-000000000001'))->>'id')::uuid))->>'number' = '5003'
  then 'ok' else 'FAIL' end || ' numbers are never reused: the new check is 5003';
\echo 'expect 2 ERRORs: the log cannot be changed or deleted'
reset role;
update check_events set note = 'x';
delete from check_events;
select case when count(*) >= 10 then 'ok' else 'FAIL' end || ' every step is in the log (' || count(*) || ' rows)' from check_events;

-- Emails for Sam: a draft waiting, a printed check, a failed one, each once.
insert into payouts (id, payee_id, show_name, amount) values ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000002', 'Test', 50);
set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
create temp table w as select check_draft('20000000-0000-0000-0000-000000000003') v;
reset role;
alter table checks disable trigger checks_guard;
update checks set drafted_at = now() - interval '5 minutes' where id = (select (v->>'id')::uuid from w);
alter table checks enable trigger checks_guard;
set role service_role;
select case when count(*) filter (where state = 'waiting') = 1 and count(*) filter (where state = 'printed') = 0
  then 'ok' else 'FAIL' end || ' Sam is told a draft is waiting' from check_alerts();
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' and only once' from check_alerts();
reset role;
