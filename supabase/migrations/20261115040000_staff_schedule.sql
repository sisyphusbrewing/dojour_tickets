-- Staff schedule on the staff site (Sam, Nov 14 2026: "We should probably also
-- phase out WhenIWork" and "do the scheduling through the staff page").
-- Staff use everything When I Work does, so this covers each piece:
--   shifts              who works when; a manager builds a week, then publishes it
--   up for grabs        someone who can't work a shift offers it, a coworker takes it
--   open shifts         a shift with nobody on it yet; anyone on the schedule can take it
--   time off            staff ask, a manager approves or declines
--   availability        each person's standing "I can't work these days"
--   notices             every change that affects someone is written to schedule_outbox;
--                       the page shows them, and schedule_notify.py sends them by
--                       email and/or text, whichever that person picked (Sam, Nov 14).
-- Everyone with a Staff login or higher can see the published schedule.
-- Managers (Grace builds it going forward, Sam Nov 14) build and change it.

-- ---------- People ----------
-- staff_roles already has one row per login. A few more facts about each one.
alter table public.staff_roles add column if not exists display_name text;
alter table public.staff_roles add column if not exists on_schedule boolean not null default true;
alter table public.staff_roles add column if not exists notify_by text not null default 'email';
alter table public.staff_roles add column if not exists notify_email text;
alter table public.staff_roles add column if not exists notify_phone text;
alter table public.staff_roles drop constraint if exists staff_roles_notify_by_check;
alter table public.staff_roles add constraint staff_roles_notify_by_check
  check (notify_by in ('email', 'text', 'both', 'none'));

-- Shared logins and the office PC's login are not people, and the owner's login
-- and door-only logins don't take shifts; a manager can switch anyone back on
-- from the page.
update public.staff_roles set on_schedule = false
 where role = 'door'
    or user_id in (select id from auth.users
                    where split_part(email, '@', 1) in ('door', 'staff', 'recorder', 'ticketing'));

create or replace function public.schedule_today()
returns date language sql stable set search_path = public as $$
  select (now() at time zone 'America/Chicago')::date
$$;

-- The name to show for a login: the name a manager typed, else the username.
create or replace function public.schedule_name(p_user uuid)
returns text language sql stable security definer set search_path = public, auth as $$
  select coalesce(nullif(trim(r.display_name), ''), split_part(u.email, '@', 1))
  from auth.users u left join public.staff_roles r on r.user_id = u.id
  where u.id = p_user
$$;

-- Everyone who can be put on a shift. Managers also see the logins that are
-- switched off, so they can switch them on.
create or replace function public.schedule_people()
returns table (user_id uuid, username text, name text, role text, on_schedule boolean)
language sql stable security definer set search_path = public, auth as $$
  select r.user_id, split_part(u.email, '@', 1)::text,
         coalesce(nullif(trim(r.display_name), ''), split_part(u.email, '@', 1))::text,
         r.role, r.on_schedule
  from public.staff_roles r join auth.users u on u.id = r.user_id
  where public.is_staff() and (r.on_schedule or public.is_manager())
  order by 3
$$;

-- A manager sets a person's name and whether they're on the schedule.
create or replace function public.schedule_set_person(p_user uuid, p_name text, p_on boolean)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  update public.staff_roles
     set display_name = nullif(trim(p_name), ''), on_schedule = coalesce(p_on, on_schedule), updated_at = now()
   where user_id = p_user;
end $$;

-- My own name and how I want to hear about schedule changes.
create or replace function public.schedule_me()
returns table (name text, notify_by text, notify_email text, notify_phone text, on_schedule boolean)
language sql stable security definer set search_path = public as $$
  select public.schedule_name(r.user_id), r.notify_by, r.notify_email, r.notify_phone, r.on_schedule
  from public.staff_roles r where r.user_id = auth.uid()
$$;

create or replace function public.schedule_save_me(p_notify_by text, p_email text, p_phone text)
returns void language plpgsql security definer set search_path = public as $$
declare v_email text := nullif(lower(trim(coalesce(p_email, ''))), '');
        v_phone text := nullif(regexp_replace(coalesce(p_phone, ''), '[^0-9]', '', 'g'), '');
begin
  if auth.uid() is null then raise exception 'Please sign in again.'; end if;
  if p_notify_by not in ('email', 'text', 'both', 'none') then raise exception 'Pick email, text, both or none.'; end if;
  if v_email is not null and v_email !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' then
    raise exception 'That email address doesn''t look right.'; end if;
  -- US mobile numbers: ten digits, with or without a leading 1.
  if v_phone is not null and length(v_phone) = 11 and left(v_phone, 1) = '1' then v_phone := substr(v_phone, 2); end if;
  if v_phone is not null and length(v_phone) <> 10 then raise exception 'That phone number should be ten digits.'; end if;
  if p_notify_by in ('email', 'both') and v_email is null then raise exception 'Add an email address first.'; end if;
  if p_notify_by in ('text', 'both') and v_phone is null then raise exception 'Add a mobile number first.'; end if;
  update public.staff_roles
     set notify_by = p_notify_by, notify_email = v_email, notify_phone = v_phone, updated_at = now()
   where user_id = auth.uid();
end $$;

-- ---------- Notices ----------
-- One row per thing a person should hear about. The schedule page lists a
-- login's own rows; schedule_notify.py emails or texts the unsent ones.
create table if not exists public.schedule_outbox (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  kind text not null,
  body text not null,
  created_at timestamptz not null default now(),
  sent_at timestamptz,          -- when the script handled it
  sent_how text,                -- 'email', 'text', 'email+text', or why it wasn't sent
  seen_at timestamptz           -- when the person dismissed it on the page
);
create index if not exists schedule_outbox_user_idx on public.schedule_outbox (user_id, created_at desc);
create index if not exists schedule_outbox_unsent_idx on public.schedule_outbox (id) where sent_at is null;
alter table public.schedule_outbox enable row level security;
drop policy if exists "Own notices" on public.schedule_outbox;
create policy "Own notices" on public.schedule_outbox for select to authenticated
  using (user_id = auth.uid());
grant select on public.schedule_outbox to authenticated;

create or replace function public.schedule_tell(p_user uuid, p_kind text, p_body text)
returns void language sql security definer set search_path = public as $$
  insert into public.schedule_outbox (user_id, kind, body)
  select p_user, p_kind, p_body where p_user is not null
$$;

-- Tell every manager (and anyone else on the schedule, when p_everyone).
create or replace function public.schedule_tell_group(p_everyone boolean, p_except uuid, p_kind text, p_body text)
returns void language sql security definer set search_path = public as $$
  insert into public.schedule_outbox (user_id, kind, body)
  select r.user_id, p_kind, p_body from public.staff_roles r
  where (r.role = 'manager' or (p_everyone and r.on_schedule and r.role <> 'door'))
    and r.user_id is distinct from p_except
$$;

create or replace function public.schedule_dismiss(p_ids bigint[])
returns void language sql security definer set search_path = public as $$
  update public.schedule_outbox set seen_at = now()
   where user_id = auth.uid() and id = any (p_ids) and seen_at is null
$$;

-- ---------- Shifts ----------
create table if not exists public.shifts (
  id bigint generated always as identity primary key,
  work_date date not null,
  start_time time not null,
  end_time time,                               -- empty = "until close"
  position text not null default 'Bar',
  user_id uuid references auth.users (id) on delete set null,   -- empty = open shift
  note text not null default '',
  published boolean not null default false,    -- staff only see published shifts
  up_for_grabs boolean not null default false, -- the person on it wants someone to take it
  reminded_at timestamptz,                     -- when the day-of reminder went out
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists shifts_date_idx on public.shifts (work_date);
create index if not exists shifts_user_idx on public.shifts (user_id, work_date);
alter table public.shifts enable row level security;
drop policy if exists "Staff see the published schedule" on public.shifts;
create policy "Staff see the published schedule" on public.shifts for select to authenticated
  using ((select public.is_staff()) and (published or (select public.is_manager())));
drop policy if exists "Managers add shifts" on public.shifts;
create policy "Managers add shifts" on public.shifts for insert to authenticated
  with check ((select public.is_manager()));
drop policy if exists "Managers change shifts" on public.shifts;
create policy "Managers change shifts" on public.shifts for update to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
drop policy if exists "Managers remove shifts" on public.shifts;
create policy "Managers remove shifts" on public.shifts for delete to authenticated
  using ((select public.is_manager()));
grant select, insert, update, delete on public.shifts to authenticated;

-- "Fri Nov 20, 4:00 PM to close (Bar)"
create or replace function public.shift_label(p_date date, p_start time, p_end time, p_position text)
returns text language sql stable set search_path = public as $$
  select to_char(p_date, 'Dy Mon FMDD') || ', ' || to_char(p_start, 'FMHH12:MI AM') || ' to ' ||
         coalesce(to_char(p_end, 'FMHH12:MI AM'), 'close') || ' (' || p_position || ')'
$$;

-- When a manager changes a shift that staff can already see, tell whoever it
-- affects. Nothing is sent for drafts, for past days, or to the person who
-- made the change themselves. Publishing a week and taking/offering a shift
-- write their own, better notices and switch this one off while they work.
create or replace function public.shifts_notify()
returns trigger language plpgsql security definer set search_path = public as $$
declare me uuid := auth.uid();
        today date := public.schedule_today();
        was_live boolean := tg_op <> 'INSERT' and old.published and old.work_date >= today;
        is_live boolean := tg_op <> 'DELETE' and new.published and new.work_date >= today;
begin
  if tg_op <> 'DELETE' then new.updated_at := now(); end if;
  if coalesce(current_setting('schedule.quiet', true), '') = '1' then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  if was_live and not is_live then
    if old.user_id is distinct from me then
      perform public.schedule_tell(old.user_id, 'shift_off',
        'You are off this shift: ' || public.shift_label(old.work_date, old.start_time, old.end_time, old.position));
    end if;
  elsif is_live and not was_live then
    if new.user_id is distinct from me then
      perform public.schedule_tell(new.user_id, 'shift_new',
        'New shift for you: ' || public.shift_label(new.work_date, new.start_time, new.end_time, new.position));
    end if;
  elsif is_live and was_live then
    if new.user_id is distinct from old.user_id then
      if old.user_id is distinct from me then
        perform public.schedule_tell(old.user_id, 'shift_off',
          'You are off this shift: ' || public.shift_label(old.work_date, old.start_time, old.end_time, old.position));
      end if;
      if new.user_id is distinct from me then
        perform public.schedule_tell(new.user_id, 'shift_new',
          'New shift for you: ' || public.shift_label(new.work_date, new.start_time, new.end_time, new.position));
      end if;
    elsif new.user_id is distinct from me
      and (new.work_date, new.start_time, new.end_time, new.position)
          is distinct from (old.work_date, old.start_time, old.end_time, old.position) then
      perform public.schedule_tell(new.user_id, 'shift_changed',
        'Your shift changed. Was ' || public.shift_label(old.work_date, old.start_time, old.end_time, old.position) ||
        '. Now ' || public.shift_label(new.work_date, new.start_time, new.end_time, new.position));
    end if;
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end $$;
drop trigger if exists shifts_notify on public.shifts;
create trigger shifts_notify before insert or update or delete on public.shifts
  for each row execute function public.shifts_notify();

-- Publish every draft shift between two dates, and tell each person their
-- shifts in one notice (plus how many open shifts are up for grabs).
create or replace function public.schedule_publish(p_from date, p_to date)
returns int language plpgsql security definer set search_path = public as $$
declare v_ids bigint[]; v_count int; v_open int; v_range text;
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  perform set_config('schedule.quiet', '1', true);
  with done as (
    update public.shifts set published = true
     where work_date between p_from and p_to and not published
    returning id)
  select coalesce(array_agg(id), '{}') into v_ids from done;
  perform set_config('schedule.quiet', '', true);
  v_count := coalesce(array_length(v_ids, 1), 0);
  select count(*) into v_open from public.shifts
   where id = any (v_ids) and user_id is null and work_date >= public.schedule_today();
  v_range := to_char(p_from, 'Mon FMDD') || ' to ' || to_char(p_to, 'Mon FMDD');
  insert into public.schedule_outbox (user_id, kind, body)
  select r.user_id, 'published',
         'The schedule for ' || v_range || ' is posted. ' ||
         coalesce('Your shifts: ' || m.mine || '.', 'You have no shifts that week.') ||
         case when v_open > 0 then ' ' || v_open || ' open shift' || case when v_open > 1 then 's are' else ' is' end ||
              ' up for grabs.' else '' end
  from public.staff_roles r
  left join lateral (
    select string_agg(public.shift_label(p.work_date, p.start_time, p.end_time, p.position), '; '
                      order by p.work_date, p.start_time) as mine
    from public.shifts p
    where p.id = any (v_ids) and p.user_id = r.user_id and p.work_date >= public.schedule_today()) m on true
  where r.on_schedule and v_count > 0 and (m.mine is not null or v_open > 0)
    and r.user_id is distinct from auth.uid();
  return v_count;
end $$;

-- "I can't work this one": offer my shift to everyone (or take the offer back).
-- It stays mine until someone takes it.
create or replace function public.shift_offer(p_shift bigint, p_on boolean)
returns void language plpgsql security definer set search_path = public as $$
declare s public.shifts;
begin
  select * into s from public.shifts where id = p_shift for update;
  if s.id is null or s.user_id is distinct from auth.uid() then raise exception 'That isn''t your shift.'; end if;
  if not s.published or s.work_date < public.schedule_today() then raise exception 'That shift is already over.'; end if;
  if s.up_for_grabs = p_on then return; end if;
  perform set_config('schedule.quiet', '1', true);
  update public.shifts set up_for_grabs = p_on where id = p_shift;
  perform set_config('schedule.quiet', '', true);
  if p_on then
    perform public.schedule_tell_group(true, auth.uid(), 'shift_offered',
      public.schedule_name(auth.uid()) || ' needs someone to take a shift: ' ||
      public.shift_label(s.work_date, s.start_time, s.end_time, s.position) || '. Take it on the schedule page.');
  end if;
end $$;

-- Take an open shift, or one a coworker offered up. First tap wins.
create or replace function public.shift_take(p_shift bigint)
returns void language plpgsql security definer set search_path = public as $$
declare s public.shifts; v_me uuid := auth.uid(); v_label text;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  if not exists (select 1 from public.staff_roles where user_id = v_me and on_schedule) then
    raise exception 'This login isn''t on the schedule. Ask a manager to add it.'; end if;
  select * into s from public.shifts where id = p_shift for update;
  if s.id is null or not s.published or s.work_date < public.schedule_today() then
    raise exception 'That shift isn''t there any more.'; end if;
  if s.user_id = v_me then raise exception 'That shift is already yours.'; end if;
  if s.user_id is not null and not s.up_for_grabs then raise exception 'Somebody already has that shift.'; end if;
  perform set_config('schedule.quiet', '1', true);
  update public.shifts set user_id = v_me, up_for_grabs = false, reminded_at = null where id = p_shift;
  perform set_config('schedule.quiet', '', true);
  v_label := public.shift_label(s.work_date, s.start_time, s.end_time, s.position);
  if s.user_id is not null then
    perform public.schedule_tell(s.user_id, 'shift_taken',
      public.schedule_name(v_me) || ' took your shift: ' || v_label || '. You are off it.');
  end if;
  perform public.schedule_tell_group(false, v_me, 'shift_taken',
    public.schedule_name(v_me) || ' took ' ||
    case when s.user_id is null then 'an open shift' else public.schedule_name(s.user_id) || '''s shift' end ||
    ': ' || v_label || '.');
end $$;

-- ---------- Time off ----------
create table if not exists public.time_off (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  start_date date not null,
  end_date date not null,
  note text not null default '',
  status text not null default 'pending' check (status in ('pending', 'approved', 'denied', 'cancelled')),
  decided_by text,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  check (end_date >= start_date)
);
create index if not exists time_off_dates_idx on public.time_off (start_date, end_date);
alter table public.time_off enable row level security;
drop policy if exists "Own time off, managers see all" on public.time_off;
create policy "Own time off, managers see all" on public.time_off for select to authenticated
  using (user_id = auth.uid() or (select public.is_manager()));
drop policy if exists "Ask for time off" on public.time_off;
create policy "Ask for time off" on public.time_off for insert to authenticated
  with check (user_id = auth.uid() and status = 'pending' and (select public.is_staff()));
drop policy if exists "Take back my request" on public.time_off;
create policy "Take back my request" on public.time_off for update to authenticated
  using (user_id = auth.uid() and status in ('pending', 'approved'))
  with check (user_id = auth.uid() and status = 'cancelled');
drop policy if exists "Managers decide" on public.time_off;
create policy "Managers decide" on public.time_off for update to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
grant select, insert, update on public.time_off to authenticated;

create or replace function public.time_off_notify()
returns trigger language plpgsql security definer set search_path = public as $$
declare v_dates text := to_char(new.start_date, 'Dy Mon FMDD') ||
          case when new.end_date > new.start_date then ' to ' || to_char(new.end_date, 'Dy Mon FMDD') else '' end;
begin
  if tg_op = 'INSERT' then
    perform public.schedule_tell_group(false, auth.uid(), 'timeoff_asked',
      public.schedule_name(new.user_id) || ' asked for time off: ' || v_dates ||
      case when new.note <> '' then ' (' || new.note || ')' else '' end || '. Answer on the schedule page.');
  elsif new.status is distinct from old.status then
    if new.status in ('approved', 'denied') and new.user_id is distinct from auth.uid() then
      perform public.schedule_tell(new.user_id, 'timeoff_' || new.status,
        'Your time off for ' || v_dates || ' was ' ||
        case new.status when 'approved' then 'approved.' else 'declined. Talk to ' || coalesce(new.decided_by, 'a manager') || '.' end);
    elsif new.status = 'cancelled' then
      perform public.schedule_tell_group(false, auth.uid(), 'timeoff_cancelled',
        public.schedule_name(new.user_id) || ' took back a time off request: ' || v_dates || '.');
    end if;
  end if;
  return new;
end $$;
drop trigger if exists time_off_notify on public.time_off;
create trigger time_off_notify after insert or update on public.time_off
  for each row execute function public.time_off_notify();

-- ---------- Availability ----------
-- Standing "I can't work these days of the week" (0 = Sunday ... 6 = Saturday)
-- plus a note ("classes until 5 on Tuesdays"). Managers see everyone's.
create table if not exists public.staff_availability (
  user_id uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  off_days smallint[] not null default '{}',
  note text not null default '',
  updated_at timestamptz not null default now()
);
alter table public.staff_availability enable row level security;
drop policy if exists "Own availability, managers see all" on public.staff_availability;
create policy "Own availability, managers see all" on public.staff_availability for select to authenticated
  using (user_id = auth.uid() or (select public.is_manager()));
drop policy if exists "Set my availability" on public.staff_availability;
create policy "Set my availability" on public.staff_availability for insert to authenticated
  with check (user_id = auth.uid() and (select public.is_staff()));
drop policy if exists "Change my availability" on public.staff_availability;
create policy "Change my availability" on public.staff_availability for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
grant select, insert, update on public.staff_availability to authenticated;

create or replace function public.staff_availability_notify()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  new.updated_at := now();
  if tg_op = 'INSERT' or new.off_days is distinct from old.off_days or new.note is distinct from old.note then
    perform public.schedule_tell_group(false, auth.uid(), 'availability',
      public.schedule_name(new.user_id) || ' changed when they can work. See it on the schedule page.');
  end if;
  return new;
end $$;
drop trigger if exists staff_availability_notify on public.staff_availability;
create trigger staff_availability_notify before insert or update on public.staff_availability
  for each row execute function public.staff_availability_notify();

-- ---------- For schedule_notify.py (the service key only) ----------
-- Queue a "you work today" reminder for each of today's shifts, once.
create or replace function public.schedule_queue_reminders()
returns int language plpgsql security definer set search_path = public as $$
declare v_count int;
begin
  with due as (
    update public.shifts set reminded_at = now()
     where work_date = public.schedule_today() and published and user_id is not null and reminded_at is null
    returning user_id, work_date, start_time, end_time, position, up_for_grabs)
  , sent as (
    insert into public.schedule_outbox (user_id, kind, body)
    select user_id, 'reminder', 'You work today: ' || public.shift_label(work_date, start_time, end_time, position) ||
           case when up_for_grabs then '. Nobody has taken it, so it is still yours.' else '.' end
    from due returning 1)
  select count(*) into v_count from sent;
  return v_count;
end $$;

-- Notices not yet sent, with how to reach each person.
create or replace function public.schedule_outbox_pending()
returns table (id bigint, user_id uuid, kind text, body text, created_at timestamptz,
               name text, notify_by text, notify_email text, notify_phone text)
language sql stable security definer set search_path = public as $$
  select o.id, o.user_id, o.kind, o.body, o.created_at, public.schedule_name(o.user_id),
         r.notify_by, r.notify_email, r.notify_phone
  from public.schedule_outbox o left join public.staff_roles r on r.user_id = o.user_id
  where o.sent_at is null order by o.id limit 200
$$;

revoke all on function public.schedule_today(), public.schedule_name(uuid), public.schedule_people(),
  public.schedule_set_person(uuid, text, boolean), public.schedule_me(), public.schedule_save_me(text, text, text),
  public.schedule_tell(uuid, text, text), public.schedule_tell_group(boolean, uuid, text, text),
  public.schedule_dismiss(bigint[]), public.shift_label(date, time, time, text), public.shifts_notify(),
  public.schedule_publish(date, date), public.shift_offer(bigint, boolean), public.shift_take(bigint),
  public.time_off_notify(), public.staff_availability_notify(), public.schedule_queue_reminders(),
  public.schedule_outbox_pending() from public, anon, authenticated;
grant execute on function public.schedule_today(), public.schedule_name(uuid), public.schedule_people(),
  public.schedule_set_person(uuid, text, boolean), public.schedule_me(), public.schedule_save_me(text, text, text),
  public.schedule_dismiss(bigint[]), public.shift_label(date, time, time, text),
  public.schedule_publish(date, date), public.shift_offer(bigint, boolean), public.shift_take(bigint)
  to authenticated;
grant execute on function public.schedule_queue_reminders(), public.schedule_outbox_pending() to service_role;

notify pgrst, 'reload schema';
