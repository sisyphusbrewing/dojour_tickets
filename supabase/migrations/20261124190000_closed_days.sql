-- Sisyphus - days we're closed (holidays) on the staff Schedule.
--
-- Sam, Nov 24 2026: "Can you mark on employee schedule we will be closed
-- Christmas Day and New Year's Day?"
--
-- Until now a holiday was only a day's "people needed" set by hand to 0, with
-- a note (Thanksgiving was set that way). Only managers and the schedule
-- builder saw it, a shift could still be put on it, and nothing reached the
-- phone calendars. From here on a day can be marked closed:
--
--   staffing_days.closed   the day is closed. It always needs nobody, and its
--                          note says why ("Closed for Christmas Day").
--   schedule_needs()       tells everyone with a staff login which days are
--                          closed (the "closed" note on that day), so the
--                          Schedule and the staff home page can say so.
--   schedule_day_close()   whoever builds the schedule marks a day closed,
--                          from the day's "People needed" box. A day with
--                          shifts on it can't be closed until they are moved
--                          or removed. schedule_need_set() (a number by hand,
--                          or back to the usual) opens the day again.
--   a rule on shifts       no shift can be added to a closed day or moved
--                          onto one, by anyone, the usual week included.
--   schedule_calendar()    hands the closed days to each person's calendar
--                          link, which shows them as all-day "Sisyphus closed"
--                          days on their phone.
--
-- Closed now: Thanksgiving (Thu Nov 26 2026), Christmas Day (Fri Dec 25 2026)
-- and New Year's Day (Fri Jan 1 2027).

alter table public.staffing_days add column if not exists closed boolean not null default false;
alter table public.staffing_days add constraint staffing_days_closed_nobody check (not closed or people = 0);

insert into public.staffing_days (day, people, note, closed, set_by, set_at) values
  ('2026-11-26', 0, 'Closed for Thanksgiving', true, 'Sam', now()),
  ('2026-12-25', 0, 'Closed for Christmas Day', true, 'Sam', now()),
  ('2027-01-01', 0, 'Closed for New Year''s Day', true, 'Sam', now())
on conflict (day) do update set people = 0, note = excluded.note, closed = true, set_by = excluded.set_by, set_at = now();

-- No shift on a closed day, however it gets there.
create or replace function public.shifts_not_on_closed_days()
returns trigger language plpgsql security definer set search_path = public as $$
declare v_note text;
begin
  if tg_op = 'UPDATE' and new.work_date = old.work_date then return new; end if;
  select note into v_note from public.staffing_days where day = new.work_date and closed;
  if found then
    raise exception '% is marked closed (%). Put the shift on another day.',
      to_char(new.work_date, 'FMDy, Mon FMDD'), coalesce(nullif(v_note, ''), 'Closed');
  end if;
  return new;
end $$;
create trigger shifts_not_on_closed_days before insert or update of work_date on public.shifts
  for each row execute function public.shifts_not_on_closed_days();

-- Set one day's number by hand, or (p_people empty) go back to what the
-- rules say for it, as before. Either one opens a closed day again.
create or replace function public.schedule_need_set(p_day date, p_people int, p_note text default '')
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.can_schedule() then raise exception 'Managers only.'; end if;
  if p_day is null then raise exception 'Which day?'; end if;
  if p_people is not null and p_people not between 0 and 40 then
    raise exception 'That number is out of range (0 to 40).'; end if;
  insert into public.staffing_days (day, people, note, closed, set_by, set_at)
  values (p_day, p_people, case when p_people is null then '' else left(trim(coalesce(p_note, '')), 120) end,
          false, public.schedule_name(auth.uid()), now())
  on conflict (day) do update set people = excluded.people, note = excluded.note, closed = false,
                                  set_by = excluded.set_by, set_at = now();
end $$;

-- Mark a day closed: nobody needed, the note says why ("Closed" if empty).
create or replace function public.schedule_day_close(p_day date, p_note text default '')
returns void language plpgsql security definer set search_path = public as $$
declare v_n int;
begin
  if not public.can_schedule() then raise exception 'Managers only.'; end if;
  if p_day is null then raise exception 'Which day?'; end if;
  select count(*) into v_n from public.shifts where work_date = p_day;
  if v_n > 0 then
    raise exception 'That day has % shift%. Move or remove % first, then mark it closed.',
      v_n, case when v_n = 1 then '' else 's' end, case when v_n = 1 then 'it' else 'them' end;
  end if;
  insert into public.staffing_days (day, people, note, closed, set_by, set_at)
  values (p_day, 0, left(coalesce(nullif(trim(coalesce(p_note, '')), ''), 'Closed'), 120), true,
          public.schedule_name(auth.uid()), now())
  on conflict (day) do update set people = 0, note = excluded.note, closed = true,
                                  set_by = excluded.set_by, set_at = now();
end $$;
revoke all on function public.schedule_day_close(date, text) from public, anon, authenticated;
grant execute on function public.schedule_day_close(date, text) to authenticated;

-- schedule_needs(), as in 20261117230000_early_show_start.sql (asking
-- can_schedule(), as 20261118060000_schedule_builder.sql made it), plus
-- "closed": the day's note when we're closed, for every staff login.
create or replace function public.schedule_needs(p_from date, p_to date)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare s public.staffing_settings;
        v_mgr boolean := public.can_schedule();
        v_today date := public.schedule_today();
        v_show_runs constant int := 120;     -- minutes a show keeps the room going after it starts
        v_early_at constant int := 18 * 60;  -- 6:00 PM: a show at this time or earlier is an early show...
        v_early_lead constant int := 60;     -- ...and its extra person starts this many minutes before (Sam, Nov 17 2026)
        v_days jsonb := '[]'::jsonb;
        d date;
        v_hrs jsonb; v_open int; v_close int;
        v_events jsonb; v_paid int; v_free int;
        v_last int; v_start int; v_start_paid int; v_start_free int; v_top_sold int;
        v_paid_title text; v_free_title text;
        v_from int; v_to int; v_base int; v_x_show int; v_x_free int; v_full boolean;
        v_parts jsonb; v_rule int; v_set public.staffing_days; v_day jsonb;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  if p_from is null or p_to is null or p_to < p_from or p_to - p_from > 62 then
    raise exception 'Ask for two months or less.'; end if;
  select * into s from public.staffing_settings;

  for d in select generate_series(p_from, p_to, interval '1 day')::date loop
    v_hrs := s.hours -> lower(to_char(d, 'Dy'));
    v_open := extract(epoch from (v_hrs ->> 0)::time)::int / 60;
    v_close := extract(epoch from (v_hrs ->> 1)::time)::int / 60;

    -- x.m is when a show starts and x.come is when its extra person should
    -- be here, both in minutes after midnight.
    select coalesce(jsonb_agg(jsonb_build_object('title', x.title, 'at', x.starts_at,
                      'time', to_char(x.local, 'FMHH12:MI AM'), 'free', x.free, 'sold', x.sold)
                      order by x.starts_at, x.title), '[]'::jsonb),
           count(*) filter (where not x.free), count(*) filter (where x.free),
           max(x.m), min(x.come), min(x.come) filter (where not x.free), min(x.come) filter (where x.free),
           coalesce(max(x.sold) filter (where not x.free), 0),
           (array_agg(x.title order by x.starts_at) filter (where not x.free))[1],
           (array_agg(x.title order by x.starts_at) filter (where x.free))[1]
      into v_events, v_paid, v_free, v_last, v_start, v_start_paid, v_start_free, v_top_sold, v_paid_title, v_free_title
      from (
        select h.*, h.m - case when h.m <= v_early_at then v_early_lead else s.lead_minutes end as come
          from (
            select g.title, g.starts_at, g.starts_at at time zone 'America/Chicago' as local,
                   (extract(epoch from (g.starts_at at time zone 'America/Chicago')::time)::int / 60) as m,
                   g.free,
                   coalesce((select sum(coalesce(t.tickets, 1)) from public.tickets t
                              where trim(t.show_title) = g.title and trim(t.show_date) = g.date_text
                                and (t.source = 'Website' or (t.source = 'Dojour' and coalesce(trim(t.email), '') <> ''))), 0)::int as sold
              from (
                -- One row per showtime: General and Premium seats are one show.
                select trim(e.show_title) as title, e.starts_at, trim(e.date_text) as date_text, max(e.price) = 0 as free
                  from public.exchange_showtimes e
                 where (e.starts_at at time zone 'America/Chicago')::date = d
                   and d >= v_today
                   and e.show_title !~* '^\s*cancel'
                 group by 1, 2, 3
              ) g
          ) h
      ) x;

    v_day := jsonb_build_object('day', d, 'open', v_hrs, 'events', v_events,
               'closed', (select coalesce(nullif(c.note, ''), 'Closed') from public.staffing_days c where c.day = d and c.closed));

    if v_mgr and d >= v_today then
      -- The stretch of the day somebody has to be here for.
      v_from := least(v_open, v_start);
      v_to := greatest(v_close, v_last + v_show_runs);
      v_parts := '[]'::jsonb;
      v_rule := 0;
      if v_from is not null then
        v_base := s.open_people * case when (v_to - v_from) > s.split_over_hours * 60 then 2 else 1 end;
        if v_base > 0 then
          v_parts := v_parts || jsonb_build_object('why', case when v_open is null then 'closed' else 'open' end,
                       'people', v_base, 'from', v_from, 'to', v_to, 'split', (v_to - v_from) > s.split_over_hours * 60);
        end if;
        v_full := v_paid > 0 and v_top_sold >= s.full_at and s.full_extra > 0;
        v_x_show := case when v_paid > 0 then s.show_extra + case when v_full then s.full_extra else 0 end else 0 end;
        v_x_free := case when v_free > 0 then s.free_extra else 0 end;
        if v_x_show > 0 and v_x_show >= v_x_free then
          v_parts := v_parts || jsonb_build_object('why', 'show', 'people', v_x_show, 'from', v_start_paid,
                       'title', v_paid_title, 'full', v_full);
        elsif v_x_free > 0 then
          v_parts := v_parts || jsonb_build_object('why', 'free', 'people', v_x_free, 'from', v_start_free,
                       'title', v_free_title);
        end if;
        v_rule := v_base + greatest(v_x_show, v_x_free);
      end if;
      select * into v_set from public.staffing_days where day = d and people is not null;
      v_day := v_day || jsonb_build_object('people', coalesce(v_set.people, v_rule), 'rule_people', v_rule, 'parts', v_parts,
                 'set', case when v_set.day is null then null else
                          jsonb_build_object('people', v_set.people, 'note', v_set.note, 'by', v_set.set_by, 'closed', v_set.closed) end);
    end if;
    v_days := v_days || v_day;
  end loop;

  return jsonb_build_object('today', v_today, 'days', v_days,
           'rules', case when v_mgr then ((to_jsonb(s) - 'id') - 'hours')
                                         || jsonb_build_object('early_at', v_early_at, 'early_lead', v_early_lead)
                         else null end);
end $$;

-- schedule_calendar(), as in 20261123230000_schedule_calendar.sql, plus
-- "closed": the days we're closed, from two months back to a year ahead,
-- for the phone calendar to show as all-day days.
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
         and s.work_date >= public.schedule_today() - 60), '[]'::jsonb),
    'closed', coalesce((
      select jsonb_agg(jsonb_build_object(
               'day', to_char(c.day, 'YYYYMMDD'),
               'next', to_char(c.day + 1, 'YYYYMMDD'),
               'note', coalesce(nullif(c.note, ''), 'Closed'),
               'updated', to_char(c.set_at at time zone 'UTC', 'YYYYMMDD"T"HH24MISS"Z"'))
             order by c.day)
        from public.staffing_days c
       where c.closed and c.day between public.schedule_today() - 60 and public.schedule_today() + 366), '[]'::jsonb));
end $$;
revoke all on function public.schedule_calendar(text) from public, anon, authenticated;
grant execute on function public.schedule_calendar(text) to service_role;

notify pgrst, 'reload schema';
