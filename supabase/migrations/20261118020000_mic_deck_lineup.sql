-- The Tuesday open mic runs from the Stream Deck (Sam, Nov 17 2026: "Can we have
-- the comedy line up run through the Stream Deck for the tuesday night shows?",
-- "When it says start show it pulls the day of the show", and "it says like who
-- is on, and how much time left and they would hit start next comic when that
-- person has finished").
--
-- One call, mic_deck(move), does it all. The deck sends:
--   'load'  when START SHOW is pressed: tonight's lineup, nobody moved on.
--   'next'  when START NEXT COMIC is pressed: the comic UP NEXT goes ON NOW and
--           the comic's clock starts at their length.
--   'skip'  when UP NEXT is tapped (that comic isn't here): they go to the end
--           of the lineup; skipped a second time (or already last), they're off.
--
-- Set lengths (Sam, Nov 17 2026): drawn names (and first-timers) 3 minutes,
-- comics booked ahead (the host's picks, staff bookings) 5, the last comic 5.
-- The host opens the show and is not a spot: before the first 'next' the deck
-- says HOST IS UP.
--
-- The lineup is the same one posted online at 6:35 (booked + drawn, in running
-- order), and only once the 6:30 draw has happened; if nobody opened a page that
-- runs the draw, this runs it. Any day with no drawn lineup answers
-- {"on": false} and the deck works the way it always has.
--
-- Where the night is up to lives in mic_deck_runs, one row per night, so a deck
-- restart (or START SHOW pressed again) picks up where it was. A comic staff add
-- during the show joins the end; one who is cancelled drops out.
--
-- What it answers (the deck keeps it in its "mic" variable):
--   on        true when there is a lineup tonight
--   now       name ON NOW ('' = host is up, before the first comic)
--   now_min   their set length
--   next      name UP NEXT ('' = nobody left)
--   next_min  their set length
--   n, total  which comic of how many (0 = host)
--   left      comics still to come after the one on now

create table if not exists public.mic_deck_runs (
  mic_date   date primary key,
  ids        uuid[] not null default '{}',   -- running order for the deck, skips moved to the end
  pos        int not null default 0,         -- how many have gone up (0 = host is up)
  skipped    uuid[] not null default '{}',   -- skipped once already
  dropped    uuid[] not null default '{}',   -- skipped twice: off the lineup tonight
  updated_at timestamptz not null default now()
);
alter table public.mic_deck_runs enable row level security;
revoke all on public.mic_deck_runs from anon, authenticated;

create or replace function public.mic_deck(move text default 'load')
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_today date := (now() at time zone 'America/Chicago')::date;
  v_lineup uuid[];
  r public.mic_deck_runs;
  v_ids uuid[];
  v_skip uuid;
  v_now uuid;
  v_next uuid;
  v_len int;
begin
  if move not in ('load', 'next', 'skip') then
    raise exception 'move is load, next or skip';
  end if;
  -- The 6:30 draw, if no page has run it yet (it does nothing before 6:30 or twice).
  if not exists (select 1 from public.mic_draws where mic_date = v_today) then
    perform public.mic_draw(v_today);
  end if;
  if not exists (select 1 from public.mic_signups where mic_date = v_today and status in ('drawn', 'not_drawn')) then
    return jsonb_build_object('on', false);
  end if;
  select array_agg(id order by slot nulls last, created_at) into v_lineup
    from public.mic_signups where mic_date = v_today and status in ('booked', 'drawn');
  if v_lineup is null then
    return jsonb_build_object('on', false);
  end if;

  -- One press at a time, so two quick taps can't both move the lineup.
  perform pg_advisory_xact_lock(hashtext('mic_deck'), v_today - date '2026-01-01');
  insert into public.mic_deck_runs (mic_date, ids) values (v_today, v_lineup) on conflict (mic_date) do nothing;
  select * into r from public.mic_deck_runs where mic_date = v_today;

  -- Keep the deck's order, but only for comics still on the lineup, and add anyone new
  -- at the end. Comics already up stay where they were, so the count of who's been up
  -- doesn't shift.
  select coalesce(array_agg(x order by o), '{}') into v_ids
    from unnest(r.ids) with ordinality u(x, o)
   where x = any(v_lineup) or o <= r.pos;
  select v_ids || coalesce(array_agg(x order by o), '{}') into v_ids
    from unnest(v_lineup) with ordinality u(x, o)
   where not (x = any(v_ids)) and not (x = any(r.dropped));
  v_len := coalesce(array_length(v_ids, 1), 0);
  r.pos := least(r.pos, v_len + 1);  -- v_len + 1 = the lineup is done

  if move = 'next' then
    r.pos := least(r.pos + 1, v_len + 1);
  elsif move = 'skip' and r.pos < v_len then
    v_skip := v_ids[r.pos + 1];
    v_ids := array_remove(v_ids, v_skip);
    if not (v_skip = any(r.skipped)) and r.pos + 1 < v_len then
      v_ids := v_ids || v_skip;
      r.skipped := r.skipped || v_skip;
    else
      r.dropped := r.dropped || v_skip;
    end if;
    v_len := coalesce(array_length(v_ids, 1), 0);
  end if;

  update public.mic_deck_runs set ids = v_ids, pos = r.pos, skipped = r.skipped, dropped = r.dropped, updated_at = now()
   where mic_date = v_today;

  v_now := case when r.pos between 1 and v_len then v_ids[r.pos] end;
  v_next := case when r.pos < v_len then v_ids[r.pos + 1] end;

  if move = 'next' then
    if v_now is null then
      perform public.timer_stop();
    else
      perform public.timer_start(public.mic_deck_minutes(v_now, r.pos = v_len));
    end if;
  end if;

  return jsonb_build_object(
    'on', true,
    'now', coalesce((select name from public.mic_signups where id = v_now), ''),
    'now_min', case when v_now is null then 0 else public.mic_deck_minutes(v_now, r.pos = v_len) end,
    'next', coalesce((select name from public.mic_signups where id = v_next), ''),
    'next_min', case when v_next is null then 0 else public.mic_deck_minutes(v_next, r.pos + 1 = v_len) end,
    'n', least(r.pos, v_len),
    'total', v_len,
    'left', greatest(v_len - r.pos, 0),
    'done', r.pos > v_len);
end $$;

-- How long a comic's set is: 5 minutes if booked ahead or last up, 3 for a drawn name.
create or replace function public.mic_deck_minutes(p_id uuid, p_last boolean)
returns int language sql stable security definer set search_path = public as $$
  select case when p_last or s.status = 'booked' then 5 else 3 end
    from public.mic_signups s where s.id = p_id
$$;

revoke all on function public.mic_deck(text), public.mic_deck_minutes(uuid, boolean) from public;
grant execute on function public.mic_deck(text) to anon, authenticated, service_role;
grant execute on function public.mic_deck_minutes(uuid, boolean) to service_role;
