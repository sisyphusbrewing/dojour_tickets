-- Stage timer for comics: one row of state, a few RPCs the Stream Deck
-- (Companion Generic HTTP) and the timer page call, and realtime so the
-- screen at the back of the room reacts the moment a button is pressed.

create table if not exists public.stage_timer (
  id            int primary key default 1 check (id = 1),
  started_at    timestamptz,             -- null = stopped
  set_seconds   int not null default 600,
  light_seconds int not null default 60, -- light comes on with this much left
  light_now     boolean not null default false, -- manual light from the deck
  updated_at    timestamptz not null default now()
);
insert into public.stage_timer (id) values (1) on conflict do nothing;

alter table public.stage_timer enable row level security;
create policy stage_timer_read on public.stage_timer for select to anon, authenticated using (true);
alter table public.stage_timer replica identity full;
alter publication supabase_realtime add table public.stage_timer;

-- State plus the server clock, so every screen counts from the same time.
create or replace function public.timer_state()
returns json language sql stable security definer set search_path = public as $$
  select json_build_object(
    'started_at', started_at, 'set_seconds', set_seconds,
    'light_seconds', light_seconds, 'light_now', light_now, 'now', now())
  from public.stage_timer where id = 1;
$$;

-- Start a set. minutes null = keep the last length.
create or replace function public.timer_start(minutes int default null)
returns json language sql security definer set search_path = public as $$
  update public.stage_timer
     set started_at = now(),
         set_seconds = case when minutes is null then set_seconds
                            else least(greatest(minutes, 1), 90) * 60 end,
         light_now = false, updated_at = now()
   where id = 1;
  select public.timer_state();
$$;

create or replace function public.timer_stop()
returns json language sql security definer set search_path = public as $$
  update public.stage_timer set started_at = null, light_now = false, updated_at = now() where id = 1;
  select public.timer_state();
$$;

-- Give (or take) time: seconds can be negative.
create or replace function public.timer_add(seconds int default 60)
returns json language sql security definer set search_path = public as $$
  update public.stage_timer
     set set_seconds = greatest(set_seconds + least(greatest(seconds, -3600), 3600), 60),
         light_now = false, updated_at = now()
   where id = 1;
  select public.timer_state();
$$;

-- Flash the light now, whatever the clock says. Press again to clear.
create or replace function public.timer_light()
returns json language sql security definer set search_path = public as $$
  update public.stage_timer set light_now = not light_now, updated_at = now() where id = 1;
  select public.timer_state();
$$;

-- How many minutes before the end the light comes on.
create or replace function public.timer_set_light(minutes int default 1)
returns json language sql security definer set search_path = public as $$
  update public.stage_timer set light_seconds = least(greatest(minutes, 0), 30) * 60, updated_at = now() where id = 1;
  select public.timer_state();
$$;

revoke all on function public.timer_start(int), public.timer_stop(), public.timer_add(int),
  public.timer_light(), public.timer_set_light(int), public.timer_state() from public;
grant execute on function public.timer_start(int), public.timer_stop(), public.timer_add(int),
  public.timer_light(), public.timer_set_light(int), public.timer_state() to anon, authenticated;
