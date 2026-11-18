-- Who may read and change events_threads (the sorted events@ inbox).
-- Run it the way README.md says. Every name here is made up.
\set ON_ERROR_STOP off

-- rows as the hourly job would file them
set role service_role;
insert into events_threads (key, kind, subject, from_name, from_email, waiting_on) values
  ('gm:1', 'private', 'Holiday party?', 'Chris Planner', 'chris@acme.example', 'us'),
  ('gm:2', 'tickets', 'Wrong night', 'Sam Buyer', 'buyer@example.com', 'us');
reset role;

-- signed out: nothing (expect 1 ERROR)
set role anon;
select count(*) from events_threads;
reset role;

-- staff (not a manager): sees nothing, changes nothing
set role authenticated; select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000003', false);
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' staff sees no rows' from events_threads;
with u as (update events_threads set status = 'done' where key = 'gm:1' returning 1)
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' staff cannot make the call' from u;
reset role;

-- manager: reads, makes the call, nothing else
set role authenticated; select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
select case when count(*) = 2 then 'ok' else 'FAIL' end || ' manager sees both rows' from events_threads;
with u as (update events_threads set status = 'done', status_by = 'ggeertsema', status_at = now(), note = 'called them' where key = 'gm:1' returning 1)
select case when count(*) = 1 then 'ok' else 'FAIL' end || ' manager marks one done' from u;
-- a manager may set the call and nothing else (expect 5 ERRORs)
update events_threads set subject = 'changed' where key = 'gm:1';
update events_threads set status = 'whatever' where key = 'gm:1';
insert into events_threads (key) values ('gm:9');
delete from events_threads where key = 'gm:2';
truncate events_threads;
reset role;

-- owner counts as a manager
set role authenticated; select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000001', false);
select case when count(*) = 2 then 'ok' else 'FAIL' end || ' owner sees both rows' from events_threads;
reset role;

-- the hourly job refreshing a row keeps the manager's call
set role service_role;
insert into events_threads (key, kind, subject, waiting_on, msg_count) values ('gm:1', 'private', 'Holiday party?', 'them', 3)
  on conflict (key) do update set kind = excluded.kind, subject = excluded.subject, waiting_on = excluded.waiting_on, msg_count = excluded.msg_count;
reset role;
select case when status = 'done' and note = 'called them' and waiting_on = 'them' and updated_at >= created_at then 'ok' else 'FAIL' end || ' refresh keeps the call'
  from events_threads where key = 'gm:1';
select case when count(*) = 2 then 'ok' else 'FAIL' end || ' still two rows' from events_threads;
