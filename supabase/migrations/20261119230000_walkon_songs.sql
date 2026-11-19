-- Walk-on songs (Sam, Nov 19 2026: "Before a show we should let comics pick a
-- walk up song and we can integrate that into the deck").
--
-- Every comic on a show (host, feature, headliner) picks the song that plays
-- while they walk to the mic. The pick belongs to the comic, not to one show:
-- a host who picks once keeps that song every time they host here, until they
-- change it.
--
--   walkon_songs   one row per comic: the song, its artist and where in the
--                  song to start (comics like to start at the part that hits).
--   walkon_links   one no-login link per run on the Booking board. The page
--                  /walkon/?s=<token> lists the people on that run and lets
--                  each of them pick. Only names on the run can be picked
--                  for, so the link can't be used to change some other
--                  comic's song.
--
-- The headliner can also pick in their advance (the "Walk-on song?" stop);
-- that pick lands here too, through the trigger at the bottom.
--
-- On show night the office PC's walk-on helper (av/walkon/walkon.py) asks
-- walkon_tonight() for tonight's people in running order, finds each song on
-- Spotify and plays it when the bartender taps WALK-ON on the Stream Deck.

create table if not exists public.walkon_songs (
  name_key    text primary key,          -- the comic's name, lower case, single spaces
  comic_name  text not null,             -- as they typed it
  title       text not null,
  artist      text,
  start_sec   int not null default 0 check (start_sec between 0 and 900),
  apple_id    text,                      -- the song search result they tapped, if any
  artwork     text,                      -- its cover picture, for the page
  via         text not null default 'page' check (via in ('page', 'advance', 'staff')),
  updated_at  timestamptz not null default now()
);
alter table public.walkon_songs enable row level security;
revoke all on public.walkon_songs from anon, authenticated;
do $$ begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'walkon_songs' and policyname = 'walkon_songs_managers') then
    create policy walkon_songs_managers on public.walkon_songs for all to authenticated
      using ((select public.is_manager())) with check ((select public.is_manager()));
  end if;
end $$;
grant select, insert, update on public.walkon_songs to authenticated;

create table if not exists public.walkon_links (
  booking_show_id uuid primary key references public.booking_shows(id),
  token           text not null unique default replace(gen_random_uuid()::text, '-', ''),
  created_at      timestamptz not null default now()
);
alter table public.walkon_links enable row level security;
revoke all on public.walkon_links from anon, authenticated;

create or replace function public.walkon_key(p_name text)
returns text language sql immutable as $$
  select nullif(lower(regexp_replace(btrim(coalesce(p_name, '')), '\s+', ' ', 'g')), '')
$$;

-- The people on one run, in running order: host, then the feature(s), then the
-- headliner. "Feature" is typed by hand and sometimes holds two names
-- ("Tommy Bayer & Kellen Schneider"), so it is split on commas, "&", "+" and "and".
create or replace function public.walkon_people(p_show public.booking_shows)
returns table (pos int, role text, name text)
language sql stable set search_path = public as $$
  with raw as (
    select 1 as grp, 0 as ord, 'host' as role, btrim(p_show.host) as name
    union all
    select 2, f.ord::int, 'feature', btrim(f.name)
    from regexp_split_to_table(coalesce(p_show.feature, ''), '\s*(,|&|\+|\sand\s)\s*', 'i') with ordinality as f(name, ord)
    union all
    select 3, 0, 'headliner', btrim(p_show.act)
  ), kept as (
    select distinct on (public.walkon_key(name)) grp, ord, role, name
    from raw where public.walkon_key(name) is not null
    order by public.walkon_key(name), grp desc   -- someone listed twice keeps their latest spot
  )
  select (row_number() over (order by grp, ord))::int, role, name from kept order by grp, ord
$$;

-- A comic's song as the page and the deck see it ('{}' = nothing picked yet).
create or replace function public.walkon_song_json(p_name text)
returns jsonb language sql stable security definer set search_path = public as $$
  select coalesce((select jsonb_build_object('title', s.title, 'artist', coalesce(s.artist, ''),
                                             'start_sec', s.start_sec, 'artwork', coalesce(s.artwork, ''))
                   from public.walkon_songs s where s.name_key = public.walkon_key(p_name)), '{}'::jsonb)
$$;

-- Booking board: the link for a run (made the first time it is asked for).
create or replace function public.walkon_link(p_booking_show_id uuid)
returns text language plpgsql security definer set search_path = public as $$
declare v_token text;
begin
  if not public.is_manager() then raise exception 'Managers only'; end if;
  if not exists (select 1 from public.booking_shows where id = p_booking_show_id) then
    raise exception 'No such show on the Booking board';
  end if;
  insert into public.walkon_links (booking_show_id) values (p_booking_show_id)
  on conflict (booking_show_id) do nothing;
  select token into v_token from public.walkon_links where booking_show_id = p_booking_show_id;
  return v_token;
end $$;

-- Booking board: who on each run has picked, for the "Walk-on songs" line.
create or replace function public.walkon_board()
returns jsonb language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_manager() then raise exception 'Managers only'; end if;
  return coalesce((
    select jsonb_object_agg(b.id, jsonb_build_object(
             'token', l.token,
             'people', (select coalesce(jsonb_agg(jsonb_build_object('role', p.role, 'name', p.name,
                                                                     'song', public.walkon_song_json(p.name)) order by p.pos), '[]'::jsonb)
                        from public.walkon_people(b) p)))
    from public.booking_shows b
    left join public.walkon_links l on l.booking_show_id = b.id
    where b.stage <> 'dropped' and coalesce(b.last_night, b.first_night) >= (now() at time zone 'America/Chicago')::date - 1
  ), '{}'::jsonb);
end $$;

-- The comic's page: the run and its people with their songs. No login; the token is the key.
create or replace function public.walkon_page(p_token text)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
           'act', b.act, 'first', b.first_night, 'last', coalesce(b.last_night, b.first_night),
           'people', (select coalesce(jsonb_agg(jsonb_build_object('role', p.role, 'name', p.name,
                                                                   'song', public.walkon_song_json(p.name)) order by p.pos), '[]'::jsonb)
                      from public.walkon_people(b) p))
  from public.walkon_links l join public.booking_shows b on b.id = l.booking_show_id
  where l.token = p_token and b.stage <> 'dropped'
$$;

-- The comic's page saves a pick. Only for a name that is on that run.
create or replace function public.walkon_pick(p_token text, p_name text, p_title text, p_artist text default null,
                                              p_start_sec int default 0, p_apple_id text default null,
                                              p_artwork text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_show public.booking_shows;
  v_name text;
begin
  select b.* into v_show from public.walkon_links l join public.booking_shows b on b.id = l.booking_show_id
  where l.token = p_token and b.stage <> 'dropped';
  if v_show.id is null then raise exception 'This link is not working any more'; end if;
  select p.name into v_name from public.walkon_people(v_show) p where public.walkon_key(p.name) = public.walkon_key(p_name);
  if v_name is null then raise exception 'That name is not on this show'; end if;
  if btrim(coalesce(p_title, '')) = '' then raise exception 'Pick a song first'; end if;
  insert into public.walkon_songs (name_key, comic_name, title, artist, start_sec, apple_id, artwork, via, updated_at)
  values (public.walkon_key(v_name), v_name, left(btrim(p_title), 200), left(nullif(btrim(coalesce(p_artist, '')), ''), 200),
          least(greatest(coalesce(p_start_sec, 0), 0), 900), left(p_apple_id, 40),
          case when p_artwork like 'https://%' then left(p_artwork, 500) end, 'page', now())
  on conflict (name_key) do update set comic_name = excluded.comic_name, title = excluded.title, artist = excluded.artist,
    start_sec = excluded.start_sec, apple_id = excluded.apple_id, artwork = excluded.artwork, via = 'page', updated_at = now();
  return public.walkon_song_json(v_name);
end $$;

-- The office PC's walk-on helper: tonight's people in running order with their
-- songs. A show that runs past midnight is still "tonight" until 4 AM. The
-- names are on the ticket pages already, so the deck's public key may read it.
-- People come from the Booking board's run that covers tonight; with no run
-- there, the headliner of an advance that covers tonight. A headliner who
-- typed a song in an older advance (before the song search) gets that text as
-- "query", for the helper to look up.
create or replace function public.walkon_tonight()
returns jsonb language sql stable security definer set search_path = public as $$
  with night as (
    select ((now() at time zone 'America/Chicago') - interval '4 hours')::date as d
  ), shows as (
    select b.* from public.booking_shows b, night
    where b.stage <> 'dropped' and night.d between b.first_night and coalesce(b.last_night, b.first_night)
  ), people as (
    select distinct on (public.walkon_key(p.name)) p.pos, p.role, p.name
    from shows b cross join lateral public.walkon_people(b) p
    order by public.walkon_key(p.name), b.updated_at desc
  ), advance as (
    select a.* from public.advances a, night
    where night.d between a.show_date and coalesce(a.show_end_date, a.show_date)
    order by a.submitted_at desc nulls last limit 1
  ), everyone as (
    select pos, role, name from people
    union all
    select 1, 'headliner', coalesce(a.act_name, a.show_name) from advance a where not exists (select 1 from people)
  )
  select jsonb_build_object('night', (select d from night), 'people', coalesce(jsonb_agg(
           jsonb_build_object('role', e.role, 'name', e.name, 'song', public.walkon_song_json(e.name),
                              'query', case when e.role = 'headliner' and public.walkon_song_json(e.name) = '{}'::jsonb
                                            then coalesce((select a.data->>'walk_on' from advance a), '') else '' end)
           order by e.pos), '[]'::jsonb))
  from everyone e
$$;

-- A headliner's pick in the advance trip (data.walk_on_pick, from the same song
-- search as the page) becomes their song here.
create or replace function public.walkon_from_advance()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  v jsonb := new.data->'walk_on_pick';
  v_name text := coalesce(nullif(btrim(new.act_name), ''), nullif(btrim(new.show_name), ''));
begin
  if jsonb_typeof(v) <> 'object' or btrim(coalesce(v->>'title', '')) = '' or v_name is null then return new; end if;
  if tg_op = 'UPDATE' and old.data->'walk_on_pick' is not distinct from v then return new; end if;
  insert into public.walkon_songs (name_key, comic_name, title, artist, start_sec, apple_id, artwork, via, updated_at)
  values (public.walkon_key(v_name), v_name, left(btrim(v->>'title'), 200), left(nullif(btrim(coalesce(v->>'artist', '')), ''), 200),
          least(greatest(coalesce((v->>'start_sec')::int, 0), 0), 900), left(v->>'apple_id', 40),
          case when v->>'artwork' like 'https://%' then left(v->>'artwork', 500) end, 'advance', now())
  on conflict (name_key) do update set title = excluded.title, artist = excluded.artist, start_sec = excluded.start_sec,
    apple_id = excluded.apple_id, artwork = excluded.artwork, via = 'advance', updated_at = now();
  return new;
exception when others then
  return new;   -- a bad song pick must never stop an advance from saving
end $$;

create or replace trigger advances_walkon after insert or update of data on public.advances
  for each row execute function public.walkon_from_advance();

revoke all on function public.walkon_key(text), public.walkon_people(public.booking_shows), public.walkon_song_json(text),
  public.walkon_link(uuid), public.walkon_board(), public.walkon_page(text),
  public.walkon_pick(text, text, text, text, int, text, text), public.walkon_tonight(), public.walkon_from_advance() from public;
grant execute on function public.walkon_key(text) to anon, authenticated, service_role;
grant execute on function public.walkon_link(uuid), public.walkon_board() to authenticated;
grant execute on function public.walkon_page(text), public.walkon_pick(text, text, text, text, int, text, text),
  public.walkon_tonight() to anon, authenticated, service_role;
