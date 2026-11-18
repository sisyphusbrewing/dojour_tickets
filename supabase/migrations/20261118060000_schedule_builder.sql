-- A login that builds the schedule without being a manager (Sam, Nov 18 2026:
-- one of the bartenders "wants to take over making the schedule").
--
-- Until now only a manager login could build and post the Schedule, and a
-- manager login opens much more than that: everyone's hours and tips on the
-- Clock's Payroll tab, the Manager page with the staff logins, the Booking
-- board, supply orders. Making the schedule shouldn't need any of that.
--
-- So a staff login can be marked "builds the schedule". On the Schedule that
-- login does what a manager does:
--   - sees drafts; adds, changes and removes shifts; posts a week
--   - fills a week from the usual week, and saves a week as the usual week
--   - sees how many people each day needs, and sets one day by hand
--   - sees everyone's time off and the days they can't work, and answers time
--     off requests (never their own: a manager answers that one)
--   - sets a person's name and whether they are on the schedule
--   - is told what managers are told about the schedule (someone offered or
--     took a shift, asked for time off, changed when they can work)
-- Nothing else changes for that login anywhere: Payroll, the Manager page,
-- booking, supplies and gift cards treat it as the staff login it is. The
-- clock's notices to managers (a shift typed in by hand) stay with managers,
-- and so does changing the numbers behind "how many people a day needs".
--
-- Who builds the schedule is a mark on the login (staff_roles.builds_schedule).
-- No login can read or write that table directly, and there is no button for
-- the mark: it is set in the database on Sam's word.

alter table public.staff_roles add column if not exists builds_schedule boolean not null default false;

-- "May this login build the schedule?" Managers and the owner always may. A
-- staff login may when it carries the mark. A door login never does.
create or replace function public.can_schedule()
returns boolean language sql stable security definer set search_path = public as $$
  select auth.uid() is not null and (
    public.is_manager()
    or exists (select 1 from public.staff_roles r
                where r.user_id = auth.uid() and r.builds_schedule and public.role_rank(r.role) >= 2));
$$;
revoke all on function public.can_schedule() from public, anon;
grant execute on function public.can_schedule() to authenticated;

-- The tables' own rules: drafts, adding, changing and removing shifts, seeing
-- everyone's time off and days off.
alter policy "Staff see the published schedule" on public.shifts
  using ((select public.is_staff()) and (published or (select public.can_schedule())));
alter policy "Managers add shifts" on public.shifts
  with check ((select public.can_schedule()));
alter policy "Managers change shifts" on public.shifts
  using ((select public.can_schedule())) with check ((select public.can_schedule()));
alter policy "Managers remove shifts" on public.shifts
  using ((select public.can_schedule()));
alter policy "Own time off, managers see all" on public.time_off
  using (user_id = auth.uid() or (select public.can_schedule()));
alter policy "Own availability, managers see all" on public.staff_availability
  using (user_id = auth.uid() or (select public.can_schedule()));
-- Answering time off: a manager answers anyone's. Whoever builds the schedule
-- answers everyone's but their own.
alter policy "Managers decide" on public.time_off
  using ((select public.is_manager()) or ((select public.can_schedule()) and user_id <> auth.uid()))
  with check ((select public.is_manager()) or ((select public.can_schedule()) and user_id <> auth.uid()));

-- Who is told what managers are told. Whoever builds the schedule now hears
-- the schedule's news too. The time clock sends its own notices through here
-- (kinds starting "clock_"): those are about hours and pay, and still go to
-- managers only.
create or replace function public.schedule_tell_group(p_everyone boolean, p_except uuid, p_kind text, p_body text)
returns void language sql security definer set search_path = public as $$
  insert into public.schedule_outbox (user_id, kind, body)
  select r.user_id, p_kind, p_body from public.staff_roles r
  where (r.role = 'manager'
         or (r.builds_schedule and r.role <> 'door' and left(p_kind, 6) <> 'clock_')
         or (p_everyone and r.on_schedule and r.role <> 'door'))
    and r.user_id is distinct from p_except
$$;

-- The Schedule's functions that asked "is this a manager?" now ask "may this
-- login build the schedule?". They are long (the staffing numbers alone run
-- 150 lines), so they are not copied here a third time: this takes each one
-- as the database has it and swaps that one question. Anyone writing a new
-- version of one of these later: ask can_schedule(), not is_manager().
-- schedule_needs_rules() is left out on purpose (managers only).
do $$
declare v_names text[] := array['schedule_people', 'schedule_set_person', 'schedule_publish',
          'schedule_needs', 'schedule_need_set', 'schedule_usual', 'schedule_usual_fill', 'schedule_usual_save'];
        v_name text; v_oid oid; v_def text; v_count int;
begin
  foreach v_name in array v_names loop
    select count(*), min(p.oid) into v_count, v_oid
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public' and p.proname = v_name;
    if v_count <> 1 then
      raise exception 'Expected one function called %, found %.', v_name, v_count; end if;
    v_def := pg_get_functiondef(v_oid);
    if position('public.is_manager()' in v_def) > 0 then
      execute replace(v_def, 'public.is_manager()', 'public.can_schedule()');
    end if;
    if position('public.can_schedule()' in pg_get_functiondef(v_oid)) = 0 then
      raise exception '% does not ask can_schedule().', v_name; end if;
  end loop;
end $$;

notify pgrst, 'reload schema';
