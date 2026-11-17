-- The usual week: the template for building a week on the Schedule (Sam, Nov
-- 17 2026: "Can we pull up when i work so you can see what our schedules were
-- like before and we can use that as the template going forward?" and, on the
-- card that followed, "Yes, with the usual people").
--
-- The usual week is a short list of shifts by day of the week: when each one
-- starts and ends, the job, and who usually works it (or nobody: an open
-- shift). A manager does two things with it on the Schedule page:
--   - "Fill the usual week" puts those shifts on the week on screen as
--     drafts, which only managers see until they post. Days that are over,
--     days that already have a shift, and days set by hand to nobody (a
--     holiday) are left alone. A shift is left open when its usual person has
--     that day off, never works that day of the week, or is no longer on the
--     schedule. Nobody is told anything: drafts are quiet until posted.
--   - "Save this week as the usual week" makes the week on screen the usual
--     week from then on.
--
-- Which shifts, and who is on them, are rows in the table. They were worked
-- out from When I Work's old schedules and clock-ins and typed into the live
-- database, never into this file: this repo is public and they are people's
-- names and working hours.
--
-- Nothing is deleted here. Saving a new usual week marks the old rows as
-- replaced and keeps them, so a mistaken save can be put back.

create table if not exists public.usual_shifts (
  id bigint generated always as identity primary key,
  weekday smallint not null check (weekday between 0 and 6),    -- 0 = Sunday ... 6 = Saturday, as on the page
  start_time time not null,
  end_time time,                               -- empty = "until close"
  position text not null default 'Bar',
  user_id uuid references auth.users (id) on delete set null,   -- empty = open shift
  note text not null default '',
  saved_by text,                               -- who saved this usual week
  created_at timestamptz not null default now(),
  replaced_at timestamptz                      -- set when a newer usual week took its place
);
create index if not exists usual_shifts_now_idx on public.usual_shifts (weekday, start_time) where replaced_at is null;

alter table public.usual_shifts enable row level security;   -- no policies: functions only
-- Supabase hands every new table to the website's logins with full rights.
-- Nothing here is read or written except through the functions below.
revoke all on public.usual_shifts from anon, authenticated;

-- The Monday of the week a day is in.
create or replace function public.schedule_monday(p_day date)
returns date language sql immutable set search_path = public as $$
  select p_day - (extract(isodow from p_day)::int - 1)
$$;

-- The usual week as it stands, Monday first, for the managers' list.
create or replace function public.schedule_usual()
returns jsonb language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  return coalesce((
    select jsonb_agg(jsonb_build_object('weekday', u.weekday, 'start_time', u.start_time, 'end_time', u.end_time,
                       'position', u.position, 'user_id', u.user_id, 'note', u.note)
                     order by (u.weekday + 6) % 7, u.start_time, u.end_time nulls last, u.id)
      from public.usual_shifts u where u.replaced_at is null), '[]'::jsonb);
end $$;

-- Put the usual week on the week that p_week is in, as drafts. Says what it
-- did so the page can tell the manager:
--   added       how many draft shifts were made
--   open        the ones left open because of the person, each with the day,
--               whose shift it usually is and why ('off' = approved time off,
--               'never' = can't work that day of the week, 'gone' = no longer
--               on the schedule)
--   days_kept   days left alone because they already had a shift
--   days_closed days left alone because they were set by hand to nobody
--   days_past   days left alone because they are over
create or replace function public.schedule_usual_fill(p_week date)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_mon date;
        v_today date := public.schedule_today();
        v_have date[];
        u public.usual_shifts;
        v_day date; v_user uuid; v_why text;
        v_added int := 0;
        v_open jsonb := '[]'::jsonb;
        v_kept date[] := '{}'; v_closed date[] := '{}'; v_past date[] := '{}';
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  if p_week is null then raise exception 'Which week?'; end if;
  v_mon := public.schedule_monday(p_week);
  if v_mon + 6 < v_today then raise exception 'That week is over.'; end if;
  if not exists (select 1 from public.usual_shifts where replaced_at is null) then
    raise exception 'There is no usual week saved yet.'; end if;

  -- The days that have a shift before anything is added. Looked up once, so
  -- the second usual shift of a day isn't stopped by the first.
  select coalesce(array_agg(distinct work_date), '{}') into v_have
    from public.shifts where work_date between v_mon and v_mon + 6;

  for u in select * from public.usual_shifts where replaced_at is null
            order by (weekday + 6) % 7, start_time, id loop
    v_day := v_mon + ((u.weekday + 6) % 7);
    if v_day < v_today then
      if not v_day = any (v_past) then v_past := v_past || v_day; end if;
      continue;
    end if;
    if v_day = any (v_have) then
      if not v_day = any (v_kept) then v_kept := v_kept || v_day; end if;
      continue;
    end if;
    if exists (select 1 from public.staffing_days where day = v_day and people = 0) then
      if not v_day = any (v_closed) then v_closed := v_closed || v_day; end if;
      continue;
    end if;

    v_user := u.user_id;
    v_why := null;
    if v_user is not null then
      if not exists (select 1 from public.staff_roles r where r.user_id = v_user and r.on_schedule) then
        v_why := 'gone';
      elsif exists (select 1 from public.time_off t where t.user_id = v_user and t.status = 'approved'
                                                      and v_day between t.start_date and t.end_date) then
        v_why := 'off';
      elsif exists (select 1 from public.staff_availability a where a.user_id = v_user and u.weekday = any (a.off_days)) then
        v_why := 'never';
      end if;
      if v_why is not null then
        v_open := v_open || jsonb_build_object('day', v_day, 'user_id', v_user, 'why', v_why);
        v_user := null;
      end if;
    end if;

    insert into public.shifts (work_date, start_time, end_time, position, user_id, note)
    values (v_day, u.start_time, u.end_time, u.position, v_user, u.note);
    v_added := v_added + 1;
  end loop;

  return jsonb_build_object('added', v_added, 'open', v_open, 'days_kept', to_jsonb(v_kept),
                            'days_closed', to_jsonb(v_closed), 'days_past', to_jsonb(v_past));
end $$;

-- Make the week that p_week is in the usual week from now on: every shift on
-- it, drafts too, with the same people. The usual week it replaces is kept,
-- marked as replaced. Returns how many shifts the new usual week has.
create or replace function public.schedule_usual_save(p_week date)
returns int language plpgsql security definer set search_path = public as $$
declare v_mon date; v_count int; v_now timestamptz := now();
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  if p_week is null then raise exception 'Which week?'; end if;
  v_mon := public.schedule_monday(p_week);
  select count(*) into v_count from public.shifts where work_date between v_mon and v_mon + 6;
  if v_count = 0 then raise exception 'That week has no shifts to save.'; end if;

  update public.usual_shifts set replaced_at = v_now where replaced_at is null;
  insert into public.usual_shifts (weekday, start_time, end_time, position, user_id, note, saved_by)
  select extract(dow from s.work_date)::int, s.start_time, s.end_time, s.position, s.user_id, s.note,
         public.schedule_name(auth.uid())
    from public.shifts s
   where s.work_date between v_mon and v_mon + 6
   order by s.work_date, s.start_time, s.id;
  return v_count;
end $$;

revoke all on function public.schedule_usual() from public, anon;
revoke all on function public.schedule_usual_fill(date) from public, anon;
revoke all on function public.schedule_usual_save(date) from public, anon;
grant execute on function public.schedule_usual() to authenticated;
grant execute on function public.schedule_usual_fill(date) to authenticated;
grant execute on function public.schedule_usual_save(date) to authenticated;

notify pgrst, 'reload schema';
