\set ON_ERROR_STOP 0
\set sam '00000000-0000-0000-0000-000000000001'
\set mgr '00000000-0000-0000-0000-000000000002'
\set dee '00000000-0000-0000-0000-000000000003'
\set bld '00000000-0000-0000-0000-000000000004'
\set door '00000000-0000-0000-0000-000000000005'
-- Every check prints "ok" or "FAIL". Lines marked (expect ERROR) are meant to fail.
update staff_roles set display_name = 'Dee Stork' where user_id = :'dee';
update staff_roles set display_name = 'Gee Manager' where user_id = :'mgr';
insert into help_handbook (slug, title, min_role, sort, body) values
  ('clock', 'Clocking in and out', 'staff', 10, 'Tap the tag.'),
  ('payroll', 'The Payroll tab', 'manager', 20, 'Managers only text.'),
  ('owner', 'Owner things', 'owner', 30, 'Owner only text.');
insert into help_questions (user_id, question, answer, needs_sam) values
  (:'dee', 'How do I fix the printer?', 'Not in the handbook.', true),
  (:'mgr', 'Someone else''s question', 'x', false);
select id as dee_q from help_questions where user_id = :'dee' \gset
select id as mgr_q from help_questions where user_id = :'mgr' \gset

set role authenticated;
\echo (expect ERROR: Please sign in again, nobody signed in)
select help_note_send('idea', 'hi');
\echo (expect ERROR: permission denied, a login reading the handbook)
select * from help_handbook;
\echo (expect ERROR: permission denied, a login reading the notes)
select * from help_notes;
\echo (expect ERROR: permission denied, a login reading the questions)
select * from help_questions;

select set_config('request.jwt.claim.sub', :'door', false);
\echo (expect ERROR: Staff only, the shared door login)
select help_note_send('idea', 'hi');
\echo == the door login is told nothing about the handbook
select case when (select count(*) from help_contents()) = 0 then 'ok' else 'FAIL' end as door_contents;

select set_config('request.jwt.claim.sub', :'dee', false);
\echo == staff see the titles meant for staff only
select case when (select array_agg(title) from help_contents()) = array['Clocking in and out'] then 'ok' else 'FAIL' end as staff_contents;
\echo (expect ERROR: Owner only, staff reading Sams list)
select * from help_inbox();
\echo (expect ERROR: Owner only, staff answering a note)
select help_note_answer(1, 'x');
\echo (expect ERROR: Write something first)
select help_note_send('idea', '   ');
\echo (expect ERROR: only ideas and FYIs go without a name)
select help_note_send('need', 'I need a day off', null, true);
select help_note_send('idea', 'Popcorn machine?', null, true) as anon_id \gset
select help_note_send('broken', 'Printer is jammed', null, false, :dee_q) as broken_id \gset
\echo == a question that is not yours does not link up
select help_note_send('fyi', 'FYI', null, false, :mgr_q) as fyi_id \gset
\echo == my notes show my named notes only, not the one without a name
select case when (select count(*) from help_my_notes()) = 2 then 'ok' else 'FAIL' end as my_two;

select set_config('request.jwt.claim.sub', :'mgr', false);
\echo == a manager sees manager titles too, not the owners
select case when (select count(*) from help_contents()) = 2 then 'ok' else 'FAIL' end as mgr_contents;
select help_note_send('need', 'Sign the W-9 for Friday', current_date + 3) as need_id \gset
\echo == a manager sees only their own notes
select case when (select count(*) from help_my_notes()) = 1 then 'ok' else 'FAIL' end as mgr_own;
\echo (expect ERROR: Owner only, a manager reading Sams list)
select * from help_recent_questions();

reset role;
\echo == the linked question stayed linked for its owner and dropped for someone elses
select case when (select question_id from help_notes where id = :broken_id) is not null
             and (select question_id from help_notes where id = :fyi_id) is null then 'ok' else 'FAIL' end as links;
\echo == need_by is kept only on a "need"
select case when (select need_by from help_notes where id = :need_id) = current_date + 3 then 'ok' else 'FAIL' end as need_by;

set role service_role;
\echo == the email job gets all four new notes once, with names (none on the anonymous one)
select case when count(*) = 4 and count(from_name) = 3 and bool_or(question is not null) then 'ok' else 'FAIL' end as alerts_once
  from help_alerts();
select case when (select count(*) from help_alerts()) = 0 then 'ok' else 'FAIL' end as alerts_not_twice;
reset role;
set role authenticated;
\echo (expect ERROR: permission denied, a login running the email job)
select * from help_alerts();

select set_config('request.jwt.claim.sub', :'sam', false);
\echo == Sam sees everything, with who sent it and the helpers question
select case when (select count(*) from help_inbox()) = 4
             and (select from_name from help_inbox() where id = :broken_id) = 'Dee Stork'
             and (select question from help_inbox() where id = :broken_id) = 'How do I fix the printer?'
             and (select from_name from help_inbox() where id = :anon_id) is null then 'ok' else 'FAIL' end as inbox;
select help_note_answer(:broken_id, 'Hold FEED while you turn it on.');
select help_note_answer(:anon_id, 'Love it.');
select help_note_answer(:need_id, null, 'seen');
\echo == Sam sees the recent questions with names
select case when (select count(*) from help_recent_questions()) = 2 then 'ok' else 'FAIL' end as questions;
reset role;
\echo == the answer reached Dee notices; the anonymous note told nobody; seen told nobody
select case when (select count(*) from schedule_outbox where kind = 'help_answer') = 1
             and (select user_id from schedule_outbox where kind = 'help_answer') = :'dee'
             and (select body from schedule_outbox where kind = 'help_answer') like 'Sam answered your note ("Printer is jammed"): Hold FEED%'
            then 'ok' else 'FAIL' end as told_once;
\echo == statuses
select case when (select status from help_notes where id = :broken_id) = 'done'
             and (select status from help_notes where id = :need_id) = 'seen' then 'ok' else 'FAIL' end as statuses;
set role authenticated;
select set_config('request.jwt.claim.sub', :'dee', false);
\echo == Dee sees the answer on the page
select case when (select answer from help_my_notes() where id = :broken_id) = 'Hold FEED while you turn it on.' then 'ok' else 'FAIL' end as dee_sees;
