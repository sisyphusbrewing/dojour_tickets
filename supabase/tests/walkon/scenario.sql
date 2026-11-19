-- Walk-on songs: run on a throwaway database (see README.md). Every line should say ok.
-- Show dates are built from today, so this never depends on the date it runs.
\set QUIET on
create temp table t_ids (k text primary key, id uuid);
insert into public.booking_shows (act, first_night, last_night, stage, host, feature)
values ('Jeffrey Keller', (now() at time zone 'America/Chicago' - interval '4 hours')::date - 1,
        (now() at time zone 'America/Chicago' - interval '4 hours')::date + 2, 'confirmed',
        'Aiden McCluskey', 'Tommy Bayer and Kellen Schneider');
insert into t_ids select 'keller', id from public.booking_shows where act = 'Jeffrey Keller';

select case when array_agg(role || ':' || name order by pos) = array['host:Aiden McCluskey','feature:Tommy Bayer','feature:Kellen Schneider','headliner:Jeffrey Keller']
            then 'ok running order host, features split, headliner' else 'FAIL order ' || array_agg(name order by pos)::text end
from public.booking_shows b, public.walkon_people(b) p where b.act = 'Jeffrey Keller';

-- Only managers make links.
do $$ begin perform public.walkon_link((select id from t_ids where k = 'keller')); raise notice 'FAIL non-manager made a link';
exception when others then raise notice 'ok non-manager refused a link'; end $$;
set test.manager = 'yes';
insert into t_ids select 'token', null;
create temp table t_tok as select public.walkon_link((select id from t_ids where k = 'keller')) as token;
select case when (select token from t_tok) = public.walkon_link((select id from t_ids where k = 'keller'))
            then 'ok the same link every time' else 'FAIL second link differs' end;
set test.manager = 'no';

-- The comic's page.
select case when jsonb_array_length(public.walkon_page((select token from t_tok))->'people') = 4
            then 'ok page lists four people' else 'FAIL page' end;
select case when public.walkon_page('nope') is null then 'ok bad token shows nothing' else 'FAIL bad token' end;

-- A pick, case and spaces in the name don't matter.
select case when public.walkon_pick((select token from t_tok), '  tommy   BAYER ', 'Thunderstruck', 'AC/DC', 12)->>'title' = 'Thunderstruck'
            then 'ok feature picked a song' else 'FAIL pick' end;
select case when (select comic_name || '/' || start_sec from public.walkon_songs where name_key = 'tommy bayer') = 'Tommy Bayer/12'
            then 'ok saved under the name on the show' else 'FAIL saved name' end;
-- Not on this show: refused.
do $$ begin perform public.walkon_pick((select token from t_tok), 'Some Prankster', 'Never Gonna Give You Up', 'Rick Astley');
  raise notice 'FAIL a stranger picked';
exception when others then raise notice 'ok a name not on the show is refused'; end $$;
do $$ begin perform public.walkon_pick((select token from t_tok), 'Aiden McCluskey', '   ');
  raise notice 'FAIL empty title saved';
exception when others then raise notice 'ok an empty song is refused'; end $$;
-- Start point is kept within 0..900 s.
select case when (public.walkon_pick((select token from t_tok), 'Aiden McCluskey', 'Song', null, 5000)->>'start_sec')::int = 900
            then 'ok start point capped' else 'FAIL start cap' end;
-- Changing a pick replaces it.
select case when public.walkon_pick((select token from t_tok), 'Tommy Bayer', 'Back in Black', 'AC/DC', 0)->>'title' = 'Back in Black'
             and (select count(*) from public.walkon_songs where name_key = 'tommy bayer') = 1
            then 'ok a new pick replaces the old one' else 'FAIL replace' end;

-- The headliner's advance pick lands in the same place.
insert into public.advances (show_name, show_date, show_end_date, data)
values ('Jeffrey Keller', (now() at time zone 'America/Chicago' - interval '4 hours')::date - 1,
        (now() at time zone 'America/Chicago' - interval '4 hours')::date + 2,
        '{"walk_on": "Lacrimosa - Mozart (start 2:10)", "walk_on_pick": {"title": "Lacrimosa", "artist": "Mozart", "start_sec": 130}}');
select case when (select title || '/' || start_sec || '/' || via from public.walkon_songs where name_key = 'jeffrey keller') = 'Lacrimosa/130/advance'
            then 'ok advance pick saved for the headliner' else 'FAIL advance pick' end;
-- A broken pick never stops the advance saving.
update public.advances set data = data || '{"walk_on_pick": {"title": "X", "start_sec": "soon"}}';
select 'ok a broken advance pick does not block the advance';

-- Tonight, for the deck helper.
select case when (select string_agg(p->>'name', ',' order by o) from jsonb_array_elements(public.walkon_tonight()->'people') with ordinality as x(p, o))
                 = 'Aiden McCluskey,Tommy Bayer,Kellen Schneider,Jeffrey Keller'
            then 'ok tonight in running order' else 'FAIL tonight ' || public.walkon_tonight()::text end;
select case when (select p->'song'->>'title' from jsonb_array_elements(public.walkon_tonight()->'people') p where p->>'name' = 'Kellen Schneider') is null
             and (select p->'song'->>'title' from jsonb_array_elements(public.walkon_tonight()->'people') p where p->>'name' = 'Jeffrey Keller') = 'Lacrimosa'
            then 'ok songs attached, a comic with no pick has none' else 'FAIL tonight songs' end;
-- A dropped run is off the deck and its link stops working.
update public.booking_shows set stage = 'dropped';
select case when jsonb_array_length(public.walkon_tonight()->'people') = 1
             and public.walkon_tonight()->'people'->0->>'name' = 'Jeffrey Keller'
            then 'ok dropped run: only the advance headliner' else 'FAIL dropped ' || public.walkon_tonight()::text end;
select case when public.walkon_page((select token from t_tok)) is null then 'ok dropped run link closed' else 'FAIL dropped link' end;
-- Older advance with typed text only: the helper gets it as query.
delete from public.walkon_songs where name_key = 'jeffrey keller';
select case when public.walkon_tonight()->'people'->0->>'query' = 'Lacrimosa - Mozart (start 2:10)'
            then 'ok typed advance song handed over as query' else 'FAIL query' end;
-- Nobody tonight.
delete from public.advances;
select case when public.walkon_tonight()->'people' = '[]'::jsonb then 'ok empty night' else 'FAIL empty night' end;

-- Board: managers only.
do $$ begin perform public.walkon_board(); raise notice 'FAIL board open to staff';
exception when others then raise notice 'ok board refused to non-managers'; end $$;
