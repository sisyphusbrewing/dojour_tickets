-- Show recordings for comics (Sam, Nov 4 2026). OBS records the whole night
-- on the office PC (Stream Deck RECORD). Every press of the stage timer's
-- START and STOP CLOCK is saved here, so after the show the office PC
-- (av/recordings/split_and_share.py) can cut one clip per set, upload it to
-- Google Drive and list it in public.recordings. The next morning
-- recording_mail.py emails each headliner a link to their set. Drive files
-- are deleted after 60 days.

create table if not exists public.stage_timer_events (
  id bigint generated always as identity primary key,
  kind text not null check (kind in ('start', 'stop')),
  at timestamptz not null default now(),
  set_seconds integer
);
create index if not exists stage_timer_events_at_idx on public.stage_timer_events (at);
alter table public.stage_timer_events enable row level security;
create policy "Staff read timer events" on public.stage_timer_events for select to authenticated
  using ((select public.is_staff()));

-- A START sets started_at to now(); STOP CLOCK clears it. Time added or taken
-- away (timer_add) and WRAP IT UP leave started_at alone, so they log nothing.
create or replace function public.log_stage_timer()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.started_at is not null and new.started_at is distinct from old.started_at then
    insert into public.stage_timer_events (kind, at, set_seconds) values ('start', new.started_at, new.set_seconds);
  elsif new.started_at is null and old.started_at is not null then
    insert into public.stage_timer_events (kind, at) values ('stop', now());
  end if;
  return new;
end;
$$;
create trigger stage_timer_log after update on public.stage_timer
  for each row execute function public.log_stage_timer();

create table if not exists public.recordings (
  id bigint generated always as identity primary key,
  show_title text not null,
  starts_at timestamptz not null,          -- the showtime (show_nights.starts_at)
  part text not null,                      -- 'full', 'headliner', 'set 1', 'unsorted' ...
  clip_start timestamptz,
  clip_end timestamptz,
  drive_path text not null,
  link text,
  created_at timestamptz not null default now(),
  emailed_at timestamptz,
  emailed_to text,
  deleted_at timestamptz,
  unique (starts_at, part)
);
alter table public.recordings enable row level security;
-- The office PC signs in as the staff login "recorder" to add rows.
create policy "Staff add recordings" on public.recordings for insert to authenticated
  with check ((select public.is_staff()));
create policy "Staff update recordings" on public.recordings for update to authenticated
  using ((select public.is_staff())) with check ((select public.is_staff()));
create policy "Staff read recordings" on public.recordings for select to authenticated
  using ((select public.is_staff()));
-- show_nights is managers-only, so the recorder login asks through this.
create or replace function public.recording_shows(p_from timestamptz, p_to timestamptz)
returns table (title text, starts_at timestamptz)
language sql stable security definer set search_path = public as $$
  select title, starts_at from public.show_nights
  where starts_at between p_from and p_to and public.is_staff()
  order by starts_at;
$$;
revoke all on function public.recording_shows(timestamptz, timestamptz) from public, anon;
grant execute on function public.recording_shows(timestamptz, timestamptz) to authenticated;
grant select on public.stage_timer_events to authenticated;
grant select, insert, update on public.recordings to authenticated;
