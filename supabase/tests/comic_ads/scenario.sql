-- Checks for the comic ad results page (20261118050000_comic_ads.sql).
-- Each check prints ok or FAIL. Steps that are meant to be refused say how
-- many ERRORs to expect just above them. Made-up comics, made-up numbers.
\set ON_ERROR_STOP 0

-- Two comics, as Claude sets them up with the service key.
insert into comic_ad_clients (login, name, pass_hash) values
  ('comica', 'Comic A', extensions.crypt('first-pass', extensions.gen_salt('bf'))),
  ('comicb', 'Comic B', extensions.crypt('second-pass', extensions.gen_salt('bf')));
insert into comic_ad_shows (client_id, title, show_date, show_time, budget) values
  (1, 'Club One, Town A', current_date + 14, '7 PM', 150),
  (1, 'Club Two, Town B', current_date - 30, '8 PM', 100),
  (2, 'Club Three, Town C', current_date + 7, '9 PM', 120);
insert into comic_ad_campaigns (show_id, platform, account_id, campaign_id, spend, impressions, reach, clicks) values
  (1, 'meta', 'acct', 'm1', 10.50, 1000, 800, 40),
  (1, 'meta', 'acct', 'm2', 4.50, 500, 450, 10),
  (1, 'reddit', 'racct', 'r1', 3.00, 300, 250, 5),
  (3, 'meta', 'acct', 'm3', 99, 9999, 9000, 999);
insert into comic_ad_ticket_counts (show_id, counted_on, sold, note) values
  (1, current_date - 2, 37, 'before ads'), (1, current_date, 41, null);

set role anon;

\echo 'expect 5 ERRORs: no table can be read from a browser'
select count(*) from comic_ad_clients;
select count(*) from comic_ad_sessions;
select count(*) from comic_ad_shows;
select count(*) from comic_ad_campaigns;
select count(*) from comic_ad_ticket_counts;

\echo 'expect 1 ERROR: a made-up login'
select comic_ads_login('nobody', 'x');
select case when comic_ads_login('comica', 'wrong') is null then 'ok' else 'FAIL' end || ' a wrong password gets nothing';
\echo 'expect 1 ERROR: no report without signing in'
select comic_ads_report('made-up-code');

create temp table t (who text, token text);
insert into t values ('a', comic_ads_login('COMICA ', 'first-pass')), ('b', comic_ads_login('comicb', 'second-pass'));
select case when count(*) = 2 and bool_and(token ~ '^[0-9a-f]{48}$') then 'ok' else 'FAIL' end || ' both sign in' from t;

select case when r->>'name' = 'Comic A' and jsonb_array_length(r->'shows') = 2 then 'ok' else 'FAIL' end
  || ' comic A sees their two shows' from (select comic_ads_report((select token from t where who = 'a')) r) x;
select case when r->'shows'->0->>'title' = 'Club One, Town A' then 'ok' else 'FAIL' end
  || ' the next show comes first' from (select comic_ads_report((select token from t where who = 'a')) r) x;
select case when (p->>'spend')::numeric = 15 and (p->>'clicks')::int = 50 and (p->>'impressions')::int = 1500
            and (p->>'reach')::int = 800 then 'ok' else 'FAIL' end
  || ' two Meta campaigns add up; reach is not double-counted'
  from (select comic_ads_report((select token from t where who = 'a'))->'shows'->0->'platforms'->0 p) x;
select case when jsonb_array_length(r->'shows'->0->'platforms') = 2 and r->'shows'->0->'platforms'->1->>'platform' = 'reddit'
            and jsonb_array_length(r->'shows'->0->'tickets') = 2 and (r->'shows'->0->'tickets'->1->>'sold')::int = 41
  then 'ok' else 'FAIL' end || ' Reddit and ticket counts show'
  from (select comic_ads_report((select token from t where who = 'a')) r) x;
select case when r::text not like '%Comic B%' and r::text not like '%Club Three%' and r::text not like '%9999%'
  then 'ok' else 'FAIL' end || ' comic A never sees comic B'
  from (select comic_ads_report((select token from t where who = 'a')) r) x;
select case when r->>'name' = 'Comic B' and jsonb_array_length(r->'shows') = 1 then 'ok' else 'FAIL' end
  || ' comic B sees only their show' from (select comic_ads_report((select token from t where who = 'b')) r) x;

-- Password change.
\echo 'expect 2 ERRORs: wrong current password, too short'
select comic_ads_set_password((select token from t where who = 'a'), 'nope', 'brand-new-pass');
select comic_ads_set_password((select token from t where who = 'a'), 'first-pass', 'short');
select comic_ads_set_password((select token from t where who = 'a'), 'first-pass', 'brand-new-pass');
select case when comic_ads_login('comica', 'first-pass') is null and comic_ads_login('comica', 'brand-new-pass') is not null
  then 'ok' else 'FAIL' end || ' the new password works, the old one does not';

-- Sign out.
select comic_ads_logout((select token from t where who = 'b'));
\echo 'expect 1 ERROR: signed out'
select comic_ads_report((select token from t where who = 'b'));

-- Ten wrong passwords lock the login, even with the right one after.
select count(*) from generate_series(1, 10) g where comic_ads_login('comicb', 'wrong') is null;
\echo 'expect 1 ERROR: locked for 15 minutes'
select comic_ads_login('comicb', 'second-pass');

-- An expired session stops working.
reset role;
update comic_ad_sessions set expires_at = now() - interval '1 minute'
 where client_id = 1;
set role anon;
\echo 'expect 1 ERROR: the session ran out'
select comic_ads_report((select token from t where who = 'a'));

-- A switched-off comic can't sign in.
reset role;
update comic_ad_clients set active = false where login = 'comica';
set role anon;
\echo 'expect 1 ERROR: switched off'
select comic_ads_login('comica', 'brand-new-pass');

-- Staff logins get nothing extra either.
reset role; set role authenticated;
\echo 'expect 1 ERROR: a staff login cannot read the tables'
select count(*) from comic_ad_campaigns;
