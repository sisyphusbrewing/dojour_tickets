-- Sisyphus - your shifts on your phone's calendar.
--
-- A staff member asked (Nov 23 2026): "Is it possible ... to sync our
-- schedule from the staff portal to our iCal or Google Calendar?" Each person
-- gets a private calendar link. Apple Calendar or Google Calendar subscribes
-- to it once and keeps checking it, so a shift that is posted, changed,
-- swapped or removed on the Schedule changes on their phone too, with nothing
-- to press.
--
--   calendar_feeds          one private link code per person
--   my_calendar_feed()      the signed-in person's code (made the first time;
--                           p_new => true makes a new one and the old link stops)
--   schedule_calendar()     what the link shows: that person's posted shifts.
--                           Only the "schedule-calendar" Edge Function asks it,
--                           with the service key; no login can call it.
--
-- The link carries no login and opens nothing else: it shows one person's
-- own posted shifts and who they work with, and stops working when the login
-- is no longer staff.

create table if not exists public.calendar_feeds (
  user_id uuid primary key references auth.users (id) on delete cascade,
  token text not null unique,
  created_at timestamptz not null default now()
);
alter table public.calendar_feeds enable row level security;   -- no policies: functions only
revoke all on public.calendar_feeds from anon, authenticated;

create or replace function public.my_calendar_feed(p_new boolean default false)
returns text language plpgsql security definer set search_path = public as $$
declare v_token text;
begin
  if auth.uid() is null then raise exception 'Please sign in again.'; end if;
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  select token into v_token from public.calendar_feeds where user_id = auth.uid();
  if v_token is null or p_new then
    -- 32 random letters and digits; nobody can guess one.
    v_token := replace(gen_random_uuid()::text, '-', '');
    insert into public.calendar_feeds (user_id, token) values (auth.uid(), v_token)
      on conflict (user_id) do update set token = excluded.token, created_at = now();
  end if;
  return v_token;
end $$;
revoke all on function public.my_calendar_feed(boolean) from public, anon;
grant execute on function public.my_calendar_feed(boolean) to authenticated;

-- What one link shows: the person's posted shifts from two months back on,
-- with start and end in Minneapolis time. "Until close" ends at that day's
-- closing time from the staffing settings (six hours if the day has none);
-- a shift that ends after midnight ends the next morning,
-- the same way the Schedule counts hours. Coworkers are first names only.
-- Returns nothing for an unknown code or a login that is no longer staff.
create or replace function public.schedule_calendar(p_token text)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare v_user uuid; v_hours jsonb;
begin
  if p_token is null or p_token !~ '^[a-f0-9]{32}$' then return null; end if;
  select f.user_id into v_user
    from public.calendar_feeds f join public.staff_roles r on r.user_id = f.user_id
   where f.token = p_token and public.role_rank(r.role) >= 2;
  if v_user is null then return null; end if;
  select hours into v_hours from public.staffing_settings;

  return jsonb_build_object(
    'name', public.schedule_name(v_user),
    'shifts', coalesce((
      select jsonb_agg(jsonb_build_object(
               'id', s.id,
               'position', s.position,
               'note', s.note,
               'up_for_grabs', s.up_for_grabs,
               'until_close', s.end_time is null,
               'starts', to_char(s.work_date + s.start_time, 'YYYYMMDD"T"HH24MISS'),
               'ends', to_char(s.work_date + s.start_time + coalesce(nullif((x.end_min - x.start_min + 1440) % 1440, 0), 360) * interval '1 minute',
                               'YYYYMMDD"T"HH24MISS'),
               'updated', to_char(s.updated_at at time zone 'UTC', 'YYYYMMDD"T"HH24MISS"Z"'),
               'with', (select coalesce(jsonb_agg(distinct split_part(public.schedule_name(o.user_id), ' ', 1)), '[]'::jsonb)
                          from public.shifts o
                         where o.work_date = s.work_date and o.published and o.user_id is not null
                           and o.user_id <> v_user))
             order by s.work_date, s.start_time)
        from public.shifts s
        cross join lateral (
          select extract(epoch from s.start_time)::int / 60 as start_min,
                 coalesce(extract(epoch from s.end_time)::int / 60,
                          extract(epoch from (v_hours -> lower(to_char(s.work_date, 'Dy')) ->> 1)::time)::int / 60,
                          (extract(epoch from s.start_time)::int / 60 + 360) % 1440) as end_min
        ) x
       where s.user_id = v_user and s.published
         and s.work_date >= public.schedule_today() - 60), '[]'::jsonb));
end $$;
revoke all on function public.schedule_calendar(text) from public, anon, authenticated;
grant execute on function public.schedule_calendar(text) to service_role;
