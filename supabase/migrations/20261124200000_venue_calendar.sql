-- Sisyphus - the events@ Google Calendar on the staff Schedule.
--
-- Sam, Nov 24 2026: "Is the staff schedule showing private events too?" ...
-- "Yeah can we pull those events from the calendar?" ... "The calendar being
-- the google calendar for events@sisyphusbrewing.com".
--
-- The Schedule only knew the website's shows. The events@ calendar has those
-- too, plus what the website never sells: private parties, rentals, groups.
-- venue_calendar.py (the "Venue calendar" action, hourly) copies it here.
--
--   venue_calendar_feed     the calendar's secret iCal address, one row.
--                           Service key only; never in the repo.
--   venue_calendar          one row per event per day it touches: title,
--                           start and end (empty for an all-day event). Never
--                           the description, guests or location. A row that
--                           leaves the calendar is marked gone, not deleted.
--   venue_calendar_save()   what the action calls (service key only).
--   cal_words()             the words of a title, to tell the calendar's copy
--                           of a website show from an event of its own.
--   schedule_needs()        lists a calendar event on its day for every staff
--                           login unless the website sells a show by that name
--                           that day. One with a start time counts like a free
--                           event toward how many people the day needs.
--   schedule_calendar()     a shift on someone's phone calendar says what else
--                           is on the calendar that day.

create table if not exists public.venue_calendar_feed (
  id int primary key default 1 check (id = 1),
  ical_url text not null check (ical_url ~ '^https://calendar\.google\.com/calendar/ical/'),
  synced_at timestamptz,
  events int
);
alter table public.venue_calendar_feed enable row level security;   -- no policies: service key only
revoke all on public.venue_calendar_feed from anon, authenticated;

create table if not exists public.venue_calendar (
  uid text not null,
  day date not null,
  title text not null,
  starts_at timestamptz,
  ends_at timestamptz,
  all_day boolean not null default false,
  seen_at timestamptz not null default now(),
  gone boolean not null default false,
  primary key (uid, day)
);
create index if not exists venue_calendar_day_idx on public.venue_calendar (day);
alter table public.venue_calendar enable row level security;        -- no policies: read through the functions
revoke all on public.venue_calendar from anon, authenticated;

create or replace function public.cal_words(p_title text)
returns text[] language sql immutable set search_path = public as $$
  select coalesce(array_agg(distinct w), '{}')
    from regexp_split_to_table(lower(coalesce(p_title, '')), '[^a-z0-9]+') w
   where length(w) >= 4
     and w not in ('show', 'shows', 'comedy', 'night', 'with', 'featuring', 'live', 'tour', 'special', 'presents',
                   'doors', 'tickets', 'free', 'event', 'party', 'private', 'monday', 'tuesday', 'wednesday',
                   'thursday', 'friday', 'saturday', 'sunday', 'sisyphus')
$$;

-- Save the calendar from p_from on. Anything from p_from on that isn't in
-- p_rows any more is marked gone. An empty list is refused, so a bad read of
-- the calendar can't wipe the Schedule.
create or replace function public.venue_calendar_save(p_from date, p_rows jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_now timestamptz := clock_timestamp(); v_kept int; v_gone int;
begin
  if p_from is null or p_rows is null or jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) = 0 then
    raise exception 'Nothing to save.'; end if;
  insert into public.venue_calendar (uid, day, title, starts_at, ends_at, all_day, seen_at, gone)
  select r.uid, r.day, left(r.title, 120), r.starts_at, r.ends_at, coalesce(r.all_day, false), v_now, false
    from jsonb_to_recordset(p_rows) as r(uid text, day date, title text, starts_at timestamptz, ends_at timestamptz, all_day boolean)
   where r.uid is not null and r.day is not null and coalesce(trim(r.title), '') <> ''
  on conflict (uid, day) do update set title = excluded.title, starts_at = excluded.starts_at, ends_at = excluded.ends_at,
                                       all_day = excluded.all_day, seen_at = v_now, gone = false;
  get diagnostics v_kept = row_count;
  update public.venue_calendar set gone = true where day >= p_from and seen_at < v_now and not gone;
  get diagnostics v_gone = row_count;
  update public.venue_calendar_feed set synced_at = v_now, events = v_kept where id = 1;
  return jsonb_build_object('kept', v_kept, 'gone', v_gone);
end $$;
revoke all on function public.venue_calendar_save(date, jsonb) from public, anon, authenticated;
grant execute on function public.venue_calendar_save(date, jsonb) to service_role;

-- schedule_needs(), as in 20261124190000_closed_days.sql, plus the events@
-- calendar's own events ("cal": true; "all_day": true when it has no time).
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
        v_web text[]; v_allday jsonb;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  if p_from is null or p_to is null or p_to < p_from or p_to - p_from > 62 then
    raise exception 'Ask for two months or less.'; end if;
  select * into s from public.staffing_settings;

  for d in select generate_series(p_from, p_to, interval '1 day')::date loop
    v_hrs := s.hours -> lower(to_char(d, 'Dy'));
    v_open := extract(epoch from (v_hrs ->> 0)::time)::int / 60;
    v_close := extract(epoch from (v_hrs ->> 1)::time)::int / 60;

    -- Words in the titles of the website's shows that day, so the events@
    -- calendar's copy of a show isn't listed twice.
    v_web := coalesce((select array_agg(distinct w) from public.exchange_showtimes e, unnest(public.cal_words(e.show_title)) w
                        where (e.starts_at at time zone 'America/Chicago')::date = d and e.show_title !~* '^\s*cancel'), '{}');

    -- x.m is when a show starts and x.come is when its extra person should
    -- be here, both in minutes after midnight.
    select coalesce(jsonb_agg(jsonb_build_object('title', x.title, 'at', x.starts_at,
                      'time', to_char(x.local, 'FMHH12:MI AM'), 'free', x.free, 'sold', x.sold, 'cal', x.cal)
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
                   g.free, g.cal,
                   case when g.cal then 0 else coalesce((select sum(coalesce(t.tickets, 1)) from public.tickets t
                              where trim(t.show_title) = g.title and trim(t.show_date) = g.date_text
                                and (t.source = 'Website' or (t.source = 'Dojour' and coalesce(trim(t.email), '') <> ''))), 0)::int end as sold
              from (
                -- One row per showtime: General and Premium seats are one show.
                select trim(e.show_title) as title, e.starts_at, trim(e.date_text) as date_text, max(e.price) = 0 as free, false as cal
                  from public.exchange_showtimes e
                 where (e.starts_at at time zone 'America/Chicago')::date = d
                   and d >= v_today
                   and e.show_title !~* '^\s*cancel'
                 group by 1, 2, 3
                union all
                -- An events@ calendar event with a start time (a private party, a
                -- rental) that the website doesn't sell: listed, and counted like
                -- a free event (Sam, Nov 24 2026).
                select c.title, c.starts_at, '', true, true
                  from public.venue_calendar c
                 where c.day = d and d >= v_today and not c.gone and not c.all_day and c.starts_at is not null
                   and not (public.cal_words(c.title) && v_web)
              ) g
          ) h
      ) x;

    -- All-day events@ calendar events the website doesn't sell: listed, no time,
    -- and they don't change the day's number.
    v_allday := coalesce((select jsonb_agg(jsonb_build_object('title', c.title, 'time', null, 'cal', true, 'all_day', true) order by c.title)
                            from public.venue_calendar c
                           where c.day = d and d >= v_today and not c.gone and c.all_day
                             and not (public.cal_words(c.title) && v_web)), '[]'::jsonb);
    v_events := v_events || v_allday;

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


-- schedule_calendar(), as in 20261124190000_closed_days.sql, plus "events" on
-- each shift: what else is on the events@ calendar that day.
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
                           and o.user_id <> v_user),
               -- What else is on the events@ calendar that day (Nov 24 2026).
               'events', (select coalesce(jsonb_agg(c.title || coalesce(', ' || to_char(c.starts_at at time zone 'America/Chicago', 'FMHH12:MI AM'), '')
                                                    order by c.starts_at nulls first, c.title), '[]'::jsonb)
                            from public.venue_calendar c
                           where c.day = s.work_date and not c.gone
                             and not (public.cal_words(c.title) && coalesce((
                                   select array_agg(distinct w) from public.exchange_showtimes e, unnest(public.cal_words(e.show_title)) w
                                    where (e.starts_at at time zone 'America/Chicago')::date = s.work_date), '{}'))))
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
