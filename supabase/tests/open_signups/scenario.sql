-- A stranger who signed themselves up gets nothing; a real door login works as before.
-- Each check prints ok or FAIL.
\set ON_ERROR_STOP 0
set role authenticated;

-- The stranger: signed in, but no staff_roles row.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000099', false);
select case when my_role() is null then 'ok' else 'FAIL' end || ' a stranger has no role';
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' a stranger sees no shows' from door_shows();
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' a stranger sees no guest list' from door_guests('tonight', 'Comic Show');
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' a stranger cannot check anyone in' from door_check_in('a1', 2);
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' a stranger sees no VIP notes' from door_vip('tonight', 'Comic Show');
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' a stranger finds no other-night tickets' from other_show_matches('tonight', 'Comic Show', 'pat');
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' a stranger sees no ticket counts' from staff_show_counts();
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' a stranger sees no open mic list' from mic_signups;
\echo 'expect 1 ERROR: a stranger cannot add to the open mic list'
insert into mic_signups (name) values ('Fake');

-- The door login: same as before.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000005', false);
select case when my_role() = 'door' then 'ok' else 'FAIL' end || ' the door login is still door';
select case when count(*) = 1 then 'ok' else 'FAIL' end || ' the door sees tonight''s show' from door_shows();
select case when count(*) = 1 then 'ok' else 'FAIL' end || ' the door sees tonight''s guest list' from door_guests('tonight', 'Comic Show');
select case when count(*) = 1 then 'ok' else 'FAIL' end || ' the door sees VIP notes' from door_vip('tonight', 'Comic Show');
select case when count(*) = 1 then 'ok' else 'FAIL' end || ' the door finds the other-night ticket' from other_show_matches('tonight', 'Comic Show', 'pat');
select case when count(*) = 2 then 'ok' else 'FAIL' end || ' the door sees ticket counts' from staff_show_counts();
select case when checked_in_count = 2 then 'ok' else 'FAIL' end || ' the door checks a guest in' from door_check_in('a1', 2);
select case when count(*) = 1 then 'ok' else 'FAIL' end || ' the door sees the open mic list' from mic_signups;
insert into mic_signups (name) values ('Walk-up');
select case when count(*) = 2 then 'ok' else 'FAIL' end || ' the door adds a walk-up' from mic_signups;

-- Signed out: nothing, as before.
select set_config('request.jwt.claim.sub', '', false);
select case when count(*) = 0 then 'ok' else 'FAIL' end || ' signed out sees no guest list' from door_guests('tonight', 'Comic Show');
