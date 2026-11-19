-- Checks for "Your night" (20261119030000_guest_night.sql). Each check prints
-- ok or FAIL. Steps that are meant to be refused say how many ERRORs to
-- expect just above them. Every date is built from today, so this passes on
-- any day.
\set ON_ERROR_STOP 0

-- Tonight: an early show in an hour and a late show two hours after it, a
-- free night at the same time as the early one, and a show next week.
select to_char(now() at time zone 'America/Chicago', 'Dy, Mon FMDD') as today \gset
insert into exchange_showtimes (variant_id, show_title, date_text, starts_at, price) values
  (1, 'Big Headliner', :'today' || ' • early', now() + interval '1 hour', 25),
  (2, 'Big Headliner', :'today' || ' • late',  now() + interval '3 hours', 25),
  (3, 'Free Mic',      :'today' || ' • mic',   now() + interval '1 hour 10 minutes', 0),
  (4, 'Next Week',     'Someday • 7:00 PM',    now() + interval '7 days', 20);
-- The door list. Pat bought two for the early show on the website, Lee has
-- one for the late show from the old ticket company (no showtime id), and
-- Pat also has tickets for next week.
insert into tickets (unique_id, show_date, show_title, guest_name, email, tickets, source, ticket_type, variant_id) values
  ('web_1', :'today' || ' • early', 'Big Headliner', 'Pat O''Brien', 'Pat@Example.com ', 2, 'Website', 'General Admission', 1),
  ('dj_1',  :'today' || ' • late',  'Big Headliner', 'Lee Reserved', 'lee@example.com', 1, 'Dojour', 'Reserved Seating', null),
  ('web_2', 'Someday • 7:00 PM',    'Next Week',     'Pat O''Brien', 'pat@example.com', 4, 'Website', null, 4),
  ('old_1', 'Long ago',             'Gone Show',     'Pat O''Brien', 'pat@example.com', 2, 'Website', null, 99);

-- ===== A guest's phone: nobody signed in =====
set role anon;
select set_config('request.jwt.claim.sub', '', false);

select case when not (v->>'found')::boolean and v->'show'->>'title' = 'Big Headliner' and v->'guest' is null
            and not (v->'show'->>'late')::boolean and not (v->'show'->>'free')::boolean
            and jsonb_array_length(v->'also') = 2 then 'ok' else 'FAIL' end
  || ' no link: tonight''s next show, the two others tonight, nothing private' from (select night_look() v) x;
select case when (v->'also'->0->>'free')::boolean and (v->'also'->1->>'late')::boolean then 'ok' else 'FAIL' end
  || ' the free night reads free, the second show reads late' from (select night_look() v) x;
select case when not (night_look('0123456789abcdef0123456789abcdef')->>'found')::boolean then 'ok' else 'FAIL' end || ' a made-up key finds nobody';

-- Find my tickets: the email and the last name both have to match.
select case when night_find('pat@example.com', 'Smith') is null and night_find('nobody@example.com', 'O''Brien') is null
            and night_find('pat@example.com', '') is null and night_find('not an email', 'O''Brien') is null
            and night_find('pat@example.com', 'ri') is null and night_find('pat@example.com', '%') is null
  then 'ok' else 'FAIL' end || ' wrong name, wrong email, no name, no email, a couple of letters: nothing';
create temp table k as select night_find(' PAT@example.com', 'o''brien') as pat, night_find('lee@example.com', 'Reserved') as lee;
select case when pat ~ '^[a-f0-9]{32}$' and lee ~ '^[a-f0-9]{32}$' and pat <> lee then 'ok' else 'FAIL' end || ' Pat and Lee each get their own key' from k;
select case when night_find('pat@example.com', 'O''Brien') = pat then 'ok' else 'FAIL' end || ' asking again gives the same key (tonight''s show, not next week''s or the old one)' from k;

select case when (v->>'found')::boolean and v->'guest'->>'first' = 'Pat' and (v->'guest'->>'tickets')::int = 2
            and not (v->'guest'->>'checked_in')::boolean and not (v->'guest'->>'reserved')::boolean
            and v->'show'->>'title' = 'Big Headliner' and not (v->'show'->>'late')::boolean
            and jsonb_array_length(v->'picks') = 0 then 'ok' else 'FAIL' end
  || ' Pat''s night: first name, 2 tickets, the early show, not in yet' from (select night_look((select pat from k)) v) x;
select case when (v->'guest'->>'reserved')::boolean and (v->'show'->>'late')::boolean and v->'show'->>'starts_at' is not null
  then 'ok' else 'FAIL' end || ' Lee''s night: a reserved seat at the late show, matched by name and date' from (select night_look((select lee from k)) v) x;

-- Pat picks two beers, one for each ticket. A third is refused.
select case when jsonb_array_length(night_pick((select pat from k), 'Lager', 8)->'picks') = 1 then 'ok' else 'FAIL' end || ' first pick';
select case when jsonb_array_length(night_pick((select pat from k), '  Hard Cider  ', 8)->'picks') = 2 then 'ok' else 'FAIL' end || ' second pick';
\echo 'expect 3 ERRORs: a third for two tickets, a blank pick, a made-up key'
select night_pick((select pat from k), 'IPA', 8);
select night_pick((select lee from k), '   ', 8);
select night_pick('0123456789abcdef0123456789abcdef', 'Lager', 8);

-- Pat swaps the cider for an IPA. Lee can't touch Pat's picks.
create temp table p as select (x->>'id')::bigint id, x->>'item' item from jsonb_array_elements(night_look((select pat from k))->'picks') x;
select case when jsonb_array_length(night_unpick((select lee from k), (select id from p where item = 'Hard Cider'))->'picks') = 0
            and jsonb_array_length(night_look((select pat from k))->'picks') = 2 then 'ok' else 'FAIL' end || ' Lee''s key can''t remove Pat''s pick';
select case when jsonb_array_length(night_unpick((select pat from k), (select id from p where item = 'Hard Cider'))->'picks') = 1 then 'ok' else 'FAIL' end || ' Pat takes the cider off';
select case when (select string_agg(x->>'item', ', ') from jsonb_array_elements(night_pick((select pat from k), 'IPA', 8)->'picks') x) = 'Lager, IPA'
  then 'ok' else 'FAIL' end || ' and picks an IPA instead';

\echo 'expect 3 ERRORs: a guest can''t see the bar''s list, mark a drink poured or read the tables'
select night_bar();
select night_poured(1);
select count(*) from night_picks;

-- ===== The bar: a bartender's login =====
reset role; grant select on k, p to authenticated; set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000003', false);
select case when jsonb_array_length(v->'picks') = 2 and not (v->'picks'->0->>'here')::boolean
            and v->'picks'->0->>'guest' = 'Pat O''Brien' then 'ok' else 'FAIL' end
  || ' the bar sees Pat''s two drinks (not the one taken off), not here yet' from (select night_bar() v) x;

-- The door checks Pat in. The bar's list says so, and so does Pat's phone.
reset role; update tickets set checked_in_count = 2, checked_in = true, check_in_time = now() where unique_id = 'web_1'; set role authenticated;
select case when (v->'picks'->0->>'here')::boolean and (v->'picks'->1->>'here')::boolean then 'ok' else 'FAIL' end
  || ' checked in at the door: both drinks say pour now' from (select night_bar() v) x;

-- Handed over, one tapped by mistake and undone.
create temp table b as select (x->>'id')::bigint id, x->>'item' item from jsonb_array_elements(night_bar()->'picks') x;
select case when (select count(*) from jsonb_array_elements(night_poured((select id from b where item = 'Lager'))->'picks') x where x->>'poured_at' is not null) = 1
  then 'ok' else 'FAIL' end || ' Lager handed over';
select case when (select count(*) from jsonb_array_elements(night_poured((select id from b where item = 'Lager'), true)->'picks') x where x->>'poured_at' is not null) = 0
  then 'ok' else 'FAIL' end || ' tapped by mistake: undone';
select night_poured((select id from b where item = 'Lager')) is not null;

-- Back on Pat's phone: checked in, the Lager is poured and can't be taken off.
reset role; set role anon; select set_config('request.jwt.claim.sub', '', false);
select case when (v->'guest'->>'checked_in')::boolean and (v->'picks'->0->>'poured')::boolean and not (v->'picks'->1->>'poured')::boolean
  then 'ok' else 'FAIL' end || ' Pat''s phone: you''re in, the Lager is ready' from (select night_look((select pat from k)) v) x;
select case when jsonb_array_length(night_unpick((select pat from k), (select id from p where item = 'Lager'))->'picks') = 2
  then 'ok' else 'FAIL' end || ' a drink already handed over can''t be taken off';

-- The ticket sync deletes and re-adds door-list rows. Pat's link and picks survive it.
reset role;
delete from tickets where unique_id = 'web_1';
set role anon;
select case when not (night_look((select pat from k))->>'found')::boolean then 'ok' else 'FAIL' end || ' while the row is gone the link shows tonight''s show, no error';
reset role;
insert into tickets (unique_id, show_date, show_title, guest_name, email, tickets, source, variant_id)
  values ('web_1', :'today' || ' • early', 'Big Headliner', 'Pat O''Brien', 'pat@example.com', 2, 'Website', 1);
set role anon;
select case when jsonb_array_length(night_look((select pat from k))->'picks') = 2 then 'ok' else 'FAIL' end || ' the row comes back: same link, same picks';

-- A show that is over takes no more picks; the shared door login isn't the bar.
reset role;
update exchange_showtimes set starts_at = now() - interval '4 hours' where variant_id = 1;
update tickets set tickets = 5 where unique_id = 'web_1';
set role anon;
\echo 'expect 1 ERROR: the show is over'
select night_pick((select pat from k), 'One more', 8);
reset role; set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000005', false);
\echo 'expect 1 ERROR: the door login'
select night_bar();

-- Nothing is ever deleted, even with the service key.
reset role;
\echo 'expect 1 ERROR: no deleting'
delete from night_picks;
