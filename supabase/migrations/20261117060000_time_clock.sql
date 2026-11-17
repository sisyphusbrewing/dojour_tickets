-- Time clock, tips and payroll hours on the staff site (Sam, Nov 16 2026: "I
-- want to make the staff portal the place where people enter their shifts tied
-- to the scheduler" and "Could we have people clock in and out via tap with
-- their phones?").
--
-- Until now a shift was recorded in two places: When I Work's time clock for
-- the hours, and the "Sisyphus Tip Tracker" Google Sheet, where each person
-- typed a row per shift (date, hours, credit tips) and Sam added a "Payroll
-- Submitted" line every other week. This replaces both, and keeps the same
-- honor system the sheet had.
--
-- How it works, in plain words:
--   - A person opens the Clock page on their phone and taps one button. The
--     first tap clocks them in, the next one clocks them out. Then they type
--     the night's credit tips (now, or later when the tips are worked out).
--   - Clocking in ties itself to the shift they are on the Schedule for that
--     day, so a manager can see "scheduled 4 to 9, worked 3:58 to 9:04".
--   - A sticker (or printed sign) at the bar opens the page with a code in the
--     link. A tap made that way is marked "at the bar". The code lives here in
--     the database, never in the public repo.
--   - Forgot to clock out? The person types the time they left. Forgot to
--     clock in at all? They write the shift in. Both are marked as written in
--     and managers are told, the way a note in the tip sheet did it.
--   - Whenever a manager changes someone's hours, that person is told. Nobody's
--     hours change quietly.
--   - Payroll: Sam opens the Payroll tab and sees, per person, the hours and
--     credit tips not paid yet. "Mark payroll submitted" is the old "Payroll
--     Submitted" line: everything in it is stamped as paid. Tips or a shift
--     entered late simply show up in the next payroll.
--   - Nothing is ever deleted. A punch made by mistake is marked "removed".
-- The page only shows and asks; every rule is in the functions below.

-- ---------- The code on the bar sticker ----------
create table if not exists public.clock_settings (
  id boolean primary key default true check (id),      -- one row only
  bar_code text not null default substr(replace(gen_random_uuid()::text, '-', ''), 1, 12)
);
insert into public.clock_settings (id) values (true) on conflict (id) do nothing;
alter table public.clock_settings enable row level security;   -- no policies: functions only

-- ---------- Payrolls that have been submitted ----------
-- One row each time Sam marks a payroll as submitted (the old "Payroll
-- Submitted" line in the tip sheet). "through" is the last day it covered.
create table if not exists public.payroll_runs (
  id bigint generated always as identity primary key,
  through date not null,
  submitted_at timestamptz not null default now(),
  submitted_by text,
  undone_at timestamptz                         -- set if it was marked by mistake and taken back
);
alter table public.payroll_runs enable row level security;
drop policy if exists "Managers see payrolls" on public.payroll_runs;
create policy "Managers see payrolls" on public.payroll_runs for select to authenticated
  using ((select public.is_manager()));
grant select on public.payroll_runs to authenticated;

-- ---------- Punches ----------
create table if not exists public.time_punches (
  id bigint generated always as identity primary key,
  -- Hours are pay records: a login that has any can't be deleted out from
  -- under them (the database refuses), so a payroll never loses a person.
  user_id uuid not null references auth.users (id) on delete restrict,
  work_date date not null,                      -- the Minneapolis day they clocked in
  clock_in timestamptz not null default now(),
  clock_out timestamptz,                        -- empty = still on the clock
  tips numeric(8,2) check (tips is null or (tips >= 0 and tips < 5000)),   -- credit tips for the shift; empty = not entered yet
  note text not null default '',                -- "covered a shift", "forgot to clock in"
  shift_id bigint references public.shifts (id) on delete set null,   -- the shift on the Schedule
  in_at_bar boolean not null default false,     -- tapped the sticker at the bar
  out_at_bar boolean not null default false,
  in_typed boolean not null default false,      -- the person wrote the whole shift in afterwards
  out_typed boolean not null default false,     -- the person typed when they left
  fixed_by text,                                -- the manager who changed it, if any
  fixed_at timestamptz,
  removed boolean not null default false,       -- a mistake; kept, but not counted
  reminded_at timestamptz,                      -- when "you're still clocked in" went out
  hours_run bigint references public.payroll_runs (id),   -- the payroll these hours were paid in
  tips_run bigint references public.payroll_runs (id),    -- the payroll these tips were paid in
  created_at timestamptz not null default now()
);
create index if not exists time_punches_date_idx on public.time_punches (work_date);
create index if not exists time_punches_user_idx on public.time_punches (user_id, clock_in desc);
create index if not exists time_punches_open_idx on public.time_punches (user_id) where clock_out is null and not removed;
alter table public.time_punches enable row level security;
drop policy if exists "Own hours, managers see all" on public.time_punches;
create policy "Own hours, managers see all" on public.time_punches for select to authenticated
  using ((select public.is_staff()) and (user_id = auth.uid() or (select public.is_manager())));
grant select on public.time_punches to authenticated;   -- changes only through the functions below

-- A punch left open this long was forgotten, not worked. The next tap starts
-- a new one and the old one waits for a clock-out time.
create or replace function public.clock_forgot_after()
returns interval language sql immutable as $$ select interval '16 hours' $$;

-- Hours between two times the way payroll counts them: two decimals per shift.
create or replace function public.clock_hours(p_in timestamptz, p_out timestamptz)
returns numeric language sql immutable as $$
  select round((extract(epoch from (p_out - p_in)) / 3600.0)::numeric, 2)
$$;

-- Pay periods are two weeks, Monday to Sunday, paid the Tuesday after (ADP,
-- biweekly). Nov 2 2026 started one; this gives the Monday that starts the
-- period any day falls in.
create or replace function public.clock_period_start(p_day date)
returns date language sql immutable as $$
  select date '2026-11-02' + (floor((p_day - date '2026-11-02') / 14.0)::int * 14)
$$;

-- "Fri Nov 20, 3:58 PM to 9:04 PM", in Minneapolis time.
create or replace function public.clock_label(p_in timestamptz, p_out timestamptz)
returns text language sql stable set search_path = public as $$
  select to_char(p_in at time zone 'America/Chicago', 'Dy Mon FMDD, FMHH12:MI AM') || ' to ' ||
         coalesce(to_char(p_out at time zone 'America/Chicago', 'FMHH12:MI AM'), 'no clock-out')
$$;

-- The shift on the Schedule a person most likely means on a given day: theirs,
-- posted, starting closest to the time given.
create or replace function public.clock_shift_for(p_user uuid, p_date date, p_at timestamptz)
returns bigint language sql stable security definer set search_path = public as $$
  select s.id from public.shifts s
   where s.user_id = p_user and s.published and s.work_date = p_date
   order by abs(extract(epoch from (s.start_time - (p_at at time zone 'America/Chicago')::time))), s.id
   limit 1
$$;

-- Everything the Clock page needs to draw itself for the person signed in:
-- are they on the clock, what are they scheduled for today, which shifts
-- still need their tips, and is an old punch waiting for a clock-out time.
create or replace function public.clock_status()
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare v_me uuid := auth.uid();
        v_today date := public.schedule_today();
        v_open public.time_punches;
        v_shift public.shifts;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  select * into v_open from public.time_punches
   where user_id = v_me and clock_out is null and not removed and clock_in > now() - public.clock_forgot_after()
   order by clock_in desc limit 1;
  if v_open.shift_id is not null then
    select * into v_shift from public.shifts where id = v_open.shift_id;
  else
    select * into v_shift from public.shifts
     where id = public.clock_shift_for(v_me, coalesce(v_open.work_date, v_today), coalesce(v_open.clock_in, now()));
  end if;
  return jsonb_build_object(
    'name', public.schedule_name(v_me),
    'on_schedule', coalesce((select on_schedule from public.staff_roles where user_id = v_me), false),
    'now', now(),
    'open', case when v_open.id is null then null else
      jsonb_build_object('id', v_open.id, 'clock_in', v_open.clock_in, 'in_at_bar', v_open.in_at_bar) end,
    'shift', case when v_shift.id is null then null else
      jsonb_build_object('id', v_shift.id, 'work_date', v_shift.work_date, 'start_time', v_shift.start_time,
                         'end_time', v_shift.end_time, 'position', v_shift.position) end,
    -- The last thing they finished today, so the page can say "Clocked out at 9:04 PM".
    'last', (select jsonb_build_object('id', t.id, 'clock_in', t.clock_in, 'clock_out', t.clock_out, 'tips', t.tips)
               from public.time_punches t
              where t.user_id = v_me and not t.removed and t.clock_out is not null
                and t.clock_out > now() - interval '12 hours'
              order by t.clock_out desc limit 1),
    -- Shifts from the last five weeks that are finished but have no tips typed in.
    'need_tips', coalesce((select jsonb_agg(jsonb_build_object('id', t.id, 'work_date', t.work_date,
                              'clock_in', t.clock_in, 'clock_out', t.clock_out) order by t.clock_in desc)
               from public.time_punches t
              where t.user_id = v_me and not t.removed and t.clock_out is not null and t.tips is null
                and t.tips_run is null and t.work_date >= v_today - 35), '[]'::jsonb),
    'forgot', coalesce((select jsonb_agg(jsonb_build_object('id', t.id, 'work_date', t.work_date, 'clock_in', t.clock_in) order by t.clock_in)
               from public.time_punches t
              where t.user_id = v_me and not t.removed and t.clock_out is null
                and t.clock_in <= now() - public.clock_forgot_after()), '[]'::jsonb));
end $$;

-- The one button. Not on the clock: clock in. On the clock: clock out.
-- p_code is the code from the bar sticker's link, when the tap came from it.
-- Clocking out within two minutes of clocking in is taken as "that was a
-- mistake" and the punch is dropped, so a slip never becomes a 30-second shift.
create or replace function public.clock_punch(p_code text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_me uuid := auth.uid();
        v_at boolean;
        v_open public.time_punches;
        v_did text;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  if not exists (select 1 from public.staff_roles where user_id = v_me and on_schedule) then
    raise exception 'This login isn''t on the schedule, so it can''t clock in. Ask a manager to add it.'; end if;
  v_at := coalesce(nullif(trim(p_code), '') = (select bar_code from public.clock_settings), false);
  -- Two taps at the same instant wait their turn instead of both clocking in.
  perform pg_advisory_xact_lock(hashtext('clock:' || v_me::text));
  select * into v_open from public.time_punches
   where user_id = v_me and clock_out is null and not removed and clock_in > now() - public.clock_forgot_after()
   order by clock_in desc limit 1 for update;
  if v_open.id is not null then
    if now() - v_open.clock_in < interval '2 minutes' then
      update public.time_punches set removed = true, clock_out = now(), out_at_bar = v_at where id = v_open.id;
      v_did := 'undone';
    else
      update public.time_punches set clock_out = now(), out_at_bar = v_at where id = v_open.id;
      v_did := 'out';
    end if;
  else
    insert into public.time_punches (user_id, work_date, clock_in, shift_id, in_at_bar)
    values (v_me, public.schedule_today(), now(), public.clock_shift_for(v_me, public.schedule_today(), now()), v_at);
    v_did := 'in';
  end if;
  return public.clock_status() || jsonb_build_object('did', v_did);
end $$;

-- "I left earlier": the person types the time they left for a punch that is
-- still open (today's, or one they forgot). It is marked as typed and the
-- managers are told, so it is honest without needing a manager to do it.
create or replace function public.clock_left_at(p_id bigint, p_time time)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_me uuid := auth.uid();
        p public.time_punches;
        v_out timestamptz;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  select * into p from public.time_punches
   where id = p_id and user_id = v_me and clock_out is null and not removed for update;
  if p.id is null then raise exception 'That one is already clocked out.'; end if;
  if p_time is null then raise exception 'Pick the time you left.'; end if;
  v_out := (p.work_date + p_time) at time zone 'America/Chicago';
  if v_out <= p.clock_in then v_out := ((p.work_date + 1) + p_time) at time zone 'America/Chicago'; end if;   -- past midnight
  if v_out > now() then raise exception 'That time hasn''t happened yet.'; end if;
  if v_out - p.clock_in > public.clock_forgot_after() then
    raise exception 'That would be more than 16 hours. Check the time, or ask a manager to fix it.'; end if;
  update public.time_punches set clock_out = v_out, out_typed = true where id = p.id;
  perform public.schedule_tell_group(false, v_me, 'clock_typed',
    public.schedule_name(v_me) || ' typed in when they left: ' || public.clock_label(p.clock_in, v_out) ||
    '. Change it on the Clock page if it looks wrong.');
  return public.clock_status() || jsonb_build_object('did', 'typed');
end $$;

-- The credit tips for one of my shifts. Can be typed at clock-out or any time
-- after, and changed until those tips have gone into a payroll.
create or replace function public.clock_tips(p_id bigint, p_tips numeric)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_me uuid := auth.uid();
        p public.time_punches;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  select * into p from public.time_punches where id = p_id and user_id = v_me and not removed for update;
  if p.id is null then raise exception 'That shift isn''t there any more.'; end if;
  if p.tips_run is not null then raise exception 'Those tips were already paid. Ask a manager if they were wrong.'; end if;
  if p_tips is null or p_tips < 0 or p_tips >= 5000 then raise exception 'Type the tips as a dollar amount, like 123.45. No tips? Type 0.'; end if;
  update public.time_punches set tips = round(p_tips, 2) where id = p.id;
  return public.clock_status() || jsonb_build_object('did', 'tips');
end $$;

-- "I forgot to clock in": the person writes in a whole shift after the fact,
-- with its tips if they know them. Same honor system as a note in the old tip
-- sheet: it is marked as written in and the managers are told.
create or replace function public.clock_add_mine(p_date date, p_in time, p_out time, p_tips numeric default null, p_note text default '')
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_me uuid := auth.uid();
        v_in timestamptz;
        v_out timestamptz;
        v_clash public.time_punches;
        v_note text := left(trim(coalesce(p_note, '')), 200);
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  if not exists (select 1 from public.staff_roles where user_id = v_me and on_schedule) then
    raise exception 'This login isn''t on the schedule. Ask a manager to add it.'; end if;
  if p_date is null or p_in is null or p_out is null then raise exception 'Pick the day, when you started and when you left.'; end if;
  if p_date < public.schedule_today() - 35 then raise exception 'That''s more than five weeks back. Ask a manager to add it.'; end if;
  if p_tips is not null and (p_tips < 0 or p_tips >= 5000) then raise exception 'Type the tips as a dollar amount, like 123.45.'; end if;
  v_in := (p_date + p_in) at time zone 'America/Chicago';
  v_out := (p_date + p_out) at time zone 'America/Chicago';
  if v_out <= v_in then v_out := ((p_date + 1) + p_out) at time zone 'America/Chicago'; end if;   -- past midnight
  if v_out > now() then raise exception 'That shift isn''t over yet. Use the Clock in button instead.'; end if;
  if v_out - v_in > public.clock_forgot_after() then raise exception 'That would be more than 16 hours. Check the times.'; end if;
  perform pg_advisory_xact_lock(hashtext('clock:' || v_me::text));
  select * into v_clash from public.time_punches t
   where t.user_id = v_me and not t.removed
     and t.clock_in < v_out and coalesce(t.clock_out, t.clock_in + public.clock_forgot_after()) > v_in
   limit 1;
  if v_clash.id is not null then
    raise exception 'You already have hours then: %.', public.clock_label(v_clash.clock_in, v_clash.clock_out); end if;
  insert into public.time_punches (user_id, work_date, clock_in, clock_out, tips, note, shift_id, in_typed, out_typed)
  values (v_me, p_date, v_in, v_out, round(p_tips, 2), v_note, public.clock_shift_for(v_me, p_date, v_in), true, true);
  perform public.schedule_tell_group(false, v_me, 'clock_typed',
    public.schedule_name(v_me) || ' wrote in a shift they didn''t clock: ' || public.clock_label(v_in, v_out) ||
    case when v_note <> '' then ' (' || v_note || ')' else '' end || '. Change it on the Clock page if it looks wrong.');
  return public.clock_status() || jsonb_build_object('did', 'added');
end $$;

-- Managers: fix a punch, add one somebody missed, or remove a mistake.
--   p_id empty  = add hours for p_user on p_date
--   p_remove    = take the punch out of the count (it is kept, not deleted)
--   p_out empty = leave it without a clock-out
--   p_tips      = the tips for the shift (empty = not entered)
-- An end time at or before the start time means it ran past midnight.
-- The person whose hours changed is told what they are now. Hours or tips
-- that already went into a payroll can't be changed here; add the difference
-- as new hours so the next payroll picks it up.
create or replace function public.clock_fix(p_id bigint, p_user uuid, p_date date, p_in time, p_out time,
                                            p_tips numeric default null, p_remove boolean default false)
returns bigint language plpgsql security definer set search_path = public as $$
declare v_me uuid := auth.uid();
        p public.time_punches;
        v_in timestamptz;
        v_out timestamptz;
        v_tips numeric := round(p_tips, 2);
        v_who text := public.schedule_name(v_me);
        v_paid constant text := 'That was already paid in a payroll, so it can''t be changed. Add the difference as new hours and the next payroll picks it up.';
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  if p_id is not null then
    select * into p from public.time_punches where id = p_id for update;
    if p.id is null then raise exception 'Those hours aren''t there any more.'; end if;
  end if;
  if coalesce(p_remove, false) then
    if p.id is null then raise exception 'Pick the hours to remove.'; end if;
    if p.hours_run is not null or p.tips_run is not null then raise exception '%', v_paid; end if;
    update public.time_punches set removed = true, fixed_by = v_who, fixed_at = now() where id = p.id;
    if p.user_id is distinct from v_me and not p.removed then
      perform public.schedule_tell(p.user_id, 'clock_fixed',
        v_who || ' removed hours from your time clock: ' || public.clock_label(p.clock_in, p.clock_out) || '. Ask them if that looks wrong.');
    end if;
    return p.id;
  end if;
  if p_date is null or p_in is null then raise exception 'Pick the day and the time they clocked in.'; end if;
  if v_tips is not null and (v_tips < 0 or v_tips >= 5000) then raise exception 'Type the tips as a dollar amount, like 123.45.'; end if;
  v_in := (p_date + p_in) at time zone 'America/Chicago';
  if p_out is not null then
    v_out := (p_date + p_out) at time zone 'America/Chicago';
    if v_out <= v_in then v_out := ((p_date + 1) + p_out) at time zone 'America/Chicago'; end if;
    if v_out > now() then raise exception 'That clock-out time hasn''t happened yet.'; end if;
  end if;
  if v_in > now() then raise exception 'That clock-in time hasn''t happened yet.'; end if;
  if p.id is null then
    if p_user is null or not exists (select 1 from public.staff_roles where user_id = p_user) then
      raise exception 'Pick who the hours are for.'; end if;
    insert into public.time_punches (user_id, work_date, clock_in, clock_out, tips, shift_id, fixed_by, fixed_at)
    values (p_user, p_date, v_in, v_out, v_tips, public.clock_shift_for(p_user, p_date, v_in), v_who, now())
    returning * into p;
    if p.user_id is distinct from v_me then
      perform public.schedule_tell(p.user_id, 'clock_fixed',
        v_who || ' added hours to your time clock: ' || public.clock_label(v_in, v_out) ||
        coalesce(', $' || trim(to_char(v_tips, '999990.00')) || ' tips', '') || '.');
    end if;
  else
    -- The times are compared to the minute, because that is all the form shows.
    if p.hours_run is not null and (date_trunc('minute', v_in) is distinct from date_trunc('minute', p.clock_in)
                                    or date_trunc('minute', v_out) is distinct from date_trunc('minute', p.clock_out)) then
      raise exception '%', v_paid; end if;
    if p.tips_run is not null and v_tips is distinct from p.tips then raise exception '%', v_paid; end if;
    if p.hours_run is not null then
      update public.time_punches set tips = v_tips, fixed_by = v_who, fixed_at = now() where id = p.id;
    else
      update public.time_punches
         set work_date = p_date, clock_in = v_in, clock_out = v_out, tips = v_tips, removed = false,
             shift_id = coalesce(public.clock_shift_for(p.user_id, p_date, v_in), shift_id),
             fixed_by = v_who, fixed_at = now()
       where id = p.id;
    end if;
    if p.user_id is distinct from v_me then
      perform public.schedule_tell(p.user_id, 'clock_fixed',
        v_who || ' changed your hours. Was ' || public.clock_label(p.clock_in, p.clock_out) ||
        coalesce(', $' || trim(to_char(p.tips, '999990.00')) || ' tips', '') ||
        '. Now ' || public.clock_label(v_in, v_out) ||
        coalesce(', $' || trim(to_char(v_tips, '999990.00')) || ' tips', '') || '.');
    end if;
  end if;
  return p.id;
end $$;

-- Managers: the code that goes in the bar sticker's link.
create or replace function public.clock_bar_code()
returns text language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  return (select bar_code from public.clock_settings);
end $$;

-- ---------- Payroll ----------
-- What to type into ADP, one row per person, last name first.
--   p_run empty: everything not paid yet, up to and including p_through
--                (normally the last Sunday of the pay period). Tips or a shift
--                entered late from an earlier period are included, and counted
--                in "earlier_hours" so Sam can see why the number is bigger.
--   p_run given: exactly what went into that payroll.
-- week1 and week2 are the two weeks of the pay period, for spotting anyone
-- over 40 hours in a week.
create or replace function public.clock_payroll(p_through date default null, p_run bigint default null)
returns table (user_id uuid, name text, hours numeric, week1 numeric, week2 numeric, earlier_hours numeric,
               tips numeric, shifts int, written_in int, no_tips int, no_clock_out int)
language plpgsql stable security definer set search_path = public as $$
declare v_through date := coalesce(p_through, (select r.through from public.payroll_runs r where r.id = p_run));
        v_start date;
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  if v_through is null then raise exception 'Pick the last day of the pay period.'; end if;
  v_start := public.clock_period_start(v_through);
  return query
  with mine as (
    select t.*,
           case when t.clock_out is not null and (case when p_run is null then t.hours_run is null else t.hours_run = p_run end)
                then public.clock_hours(t.clock_in, t.clock_out) end as h,
           case when t.tips is not null and (case when p_run is null then t.tips_run is null else t.tips_run = p_run end)
                then t.tips end as tp
      from public.time_punches t
     where not t.removed and t.work_date <= v_through)
  select m.user_id, public.schedule_name(m.user_id),
         coalesce(sum(m.h), 0),
         coalesce(sum(m.h) filter (where m.work_date >= v_start and m.work_date < v_start + 7), 0),
         coalesce(sum(m.h) filter (where m.work_date >= v_start + 7), 0),
         coalesce(sum(m.h) filter (where m.work_date < v_start), 0),
         coalesce(sum(m.tp), 0),
         count(m.h)::int,
         (count(*) filter (where m.h is not null and (m.in_typed or m.out_typed)))::int,
         (count(*) filter (where p_run is null and m.h is not null and m.tips is null))::int,
         (count(*) filter (where p_run is null and m.clock_out is null and m.clock_in <= now() - public.clock_forgot_after()))::int
    from mine m
   group by m.user_id
  having count(m.h) > 0 or count(m.tp) > 0
      or count(*) filter (where p_run is null and m.clock_out is null and m.clock_in <= now() - public.clock_forgot_after()) > 0
   order by split_part(public.schedule_name(m.user_id), ' ', 2), 2;
end $$;

-- "Mark payroll submitted" (owner only): the old "Payroll Submitted" line.
-- Every finished shift and every typed tip up to p_through that hasn't been
-- paid is stamped with this payroll, so the next one starts clean.
create or replace function public.clock_payroll_submit(p_through date)
returns bigint language plpgsql security definer set search_path = public as $$
declare v_run bigint;
begin
  if public.my_role() is distinct from 'owner' then raise exception 'Only the owner marks payroll as submitted.'; end if;
  if p_through is null or p_through > public.schedule_today() then raise exception 'Pick a last day that has already happened.'; end if;
  insert into public.payroll_runs (through, submitted_by) values (p_through, public.schedule_name(auth.uid()))
  returning id into v_run;
  update public.time_punches set hours_run = v_run
   where not removed and hours_run is null and clock_out is not null and work_date <= p_through;
  update public.time_punches set tips_run = v_run
   where not removed and tips_run is null and tips is not null and work_date <= p_through;
  return v_run;
end $$;

-- Marked it by mistake? Take the latest payroll back (owner only). Its shifts
-- and tips go back to "not paid yet".
create or replace function public.clock_payroll_undo(p_run bigint)
returns void language plpgsql security definer set search_path = public as $$
begin
  if public.my_role() is distinct from 'owner' then raise exception 'Only the owner can take a payroll back.'; end if;
  if p_run is distinct from (select max(id) from public.payroll_runs where undone_at is null) then
    raise exception 'Only the most recent payroll can be taken back.'; end if;
  update public.time_punches set hours_run = null where hours_run = p_run;
  update public.time_punches set tips_run = null where tips_run = p_run;
  update public.payroll_runs set undone_at = now() where id = p_run;
end $$;

-- ---------- For schedule_notify.py (the service key only) ----------
-- "You're still clocked in": once per punch, 45 minutes after the shift on the
-- Schedule was due to end, or after 11 hours when there is no end time to go by.
create or replace function public.clock_queue_reminders()
returns int language plpgsql security definer set search_path = public as $$
declare v_count int;
begin
  with due as (
    update public.time_punches t set reminded_at = now()
     where t.clock_out is null and not t.removed and t.reminded_at is null
       and t.clock_in > now() - interval '3 days'
       and (now() > t.clock_in + interval '11 hours'
            or exists (select 1 from public.shifts s
                        where s.id = t.shift_id and s.end_time is not null
                          and now() > ((s.work_date + case when s.end_time <= s.start_time then 1 else 0 end + s.end_time)
                                       at time zone 'America/Chicago') + interval '45 minutes'))
    returning t.user_id, t.clock_in)
  , sent as (
    insert into public.schedule_outbox (user_id, kind, body)
    select user_id, 'clock_open',
           'You are still clocked in from ' || to_char(clock_in at time zone 'America/Chicago', 'Dy FMHH12:MI AM') ||
           '. Still working? Ignore this. If you have left, open the Clock page and tap "I left earlier".'
    from due returning 1)
  select count(*) into v_count from sent;
  return v_count;
end $$;

revoke all on function public.clock_forgot_after(), public.clock_hours(timestamptz, timestamptz),
  public.clock_period_start(date), public.clock_label(timestamptz, timestamptz),
  public.clock_shift_for(uuid, date, timestamptz), public.clock_status(), public.clock_punch(text),
  public.clock_left_at(bigint, time), public.clock_tips(bigint, numeric),
  public.clock_add_mine(date, time, time, numeric, text),
  public.clock_fix(bigint, uuid, date, time, time, numeric, boolean), public.clock_bar_code(),
  public.clock_payroll(date, bigint), public.clock_payroll_submit(date), public.clock_payroll_undo(bigint),
  public.clock_queue_reminders() from public, anon, authenticated;
grant execute on function public.clock_forgot_after(), public.clock_hours(timestamptz, timestamptz),
  public.clock_period_start(date), public.clock_label(timestamptz, timestamptz),
  public.clock_status(), public.clock_punch(text), public.clock_left_at(bigint, time),
  public.clock_tips(bigint, numeric), public.clock_add_mine(date, time, time, numeric, text),
  public.clock_fix(bigint, uuid, date, time, time, numeric, boolean), public.clock_bar_code(),
  public.clock_payroll(date, bigint), public.clock_payroll_submit(date), public.clock_payroll_undo(bigint)
  to authenticated;
grant execute on function public.clock_queue_reminders() to service_role;

notify pgrst, 'reload schema';
