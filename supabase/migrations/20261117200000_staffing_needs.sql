-- How many people each day needs (Sam, Nov 17 2026: "The scheduler should
-- read the calendar for upcoming events and then say how many people we need
-- to schedule because of it").
--
-- The calendar is the website's own list of upcoming showtimes
-- (exchange_showtimes, rewritten from Shopify every four hours), so a show
-- that is added, moved or taken down changes the numbers by itself. Free
-- nights (open mic, the Thursday showcase, Blingo) are on it too, at $0.
--
-- How a day's number is worked out, in plain words:
--   - While we're open, "open_people" are on at a time (1). A day that runs
--     longer than "split_over_hours" (8) is two shifts for each of them: an
--     opener and a closer, the way Friday and Saturday are worked.
--   - A night with a ticketed show needs "show_extra" more (1), starting
--     "lead_minutes" (90) before the first show.
--   - A show with "full_at" (60) or more tickets sold needs "full_extra" more
--     again (0 to start with: the clock-ins from Aug to Nov 2026 don't show a
--     third person even on sold-out nights).
--   - A night with a free event needs "free_extra" more (1), the way a second
--     person has come in around 6 on open mic Thursdays. A free event on the
--     same night as a ticketed show doesn't add again: the bigger of the two
--     counts.
--   - A show on a day we're closed still needs someone to run the bar.
--   - A manager can set any one day's number by hand (a holiday, a private
--     party that isn't on the calendar). That wins over the rules.
-- The starting numbers come from three months of When I Work clock-ins. They
-- are Sam's to change: the Schedule page has a box for managers.
--
-- The page only shows and asks; the rules are in the functions below.

-- ---------- The numbers ----------
create table if not exists public.staffing_settings (
  id boolean primary key default true check (id),      -- one row only
  open_people int not null default 1 check (open_people between 0 and 9),
  split_over_hours numeric(4,1) not null default 8 check (split_over_hours between 4 and 24),
  show_extra int not null default 1 check (show_extra between 0 and 9),
  free_extra int not null default 1 check (free_extra between 0 and 9),
  full_extra int not null default 0 check (full_extra between 0 and 9),
  full_at int not null default 60 check (full_at between 1 and 500),
  lead_minutes int not null default 90 check (lead_minutes between 0 and 360),
  -- Taproom hours from the website's Visit page, Minneapolis time. Monday is closed.
  hours jsonb not null default
    '{"tue":["16:00","21:00"],"wed":["16:00","21:00"],"thu":["16:00","23:00"],"fri":["13:00","23:00"],"sat":["13:00","23:00"],"sun":["13:00","18:00"]}',
  updated_by text,
  updated_at timestamptz not null default now()
);
insert into public.staffing_settings (id) values (true) on conflict (id) do nothing;

-- ---------- One day set by hand ----------
-- "people" empty means the day was set by hand once and has since been put
-- back to what the rules say. The row stays; nothing is deleted.
create table if not exists public.staffing_days (
  day date primary key,
  people int check (people between 0 and 40),
  note text not null default '',
  set_by text,
  set_at timestamptz not null default now()
);

alter table public.staffing_settings enable row level security;   -- no policies: functions only
alter table public.staffing_days enable row level security;
-- Supabase hands every new table to the website's logins with full rights.
-- Nothing here is read or written except through the functions below.
revoke all on public.staffing_settings, public.staffing_days from anon, authenticated;

-- We are closed on Thanksgiving (Sam, Nov 17 2026).
insert into public.staffing_days (day, people, note, set_by)
values ('2026-11-26', 0, 'Closed for Thanksgiving', 'Wilson') on conflict (day) do nothing;

-- ---------- What each day needs ----------
-- For every day from p_from to p_to: the events on the calendar (with tickets
-- sold, website and Dojour together, the venue's own holds left out) and, for
-- managers, how many people the day needs and why. Days already gone get no
-- number: the calendar only holds what's coming.
--   people       the number to schedule (the hand-set one when there is one)
--   rule_people  what the rules alone say
--   parts        the pieces of that number, for the page to put into words
--   set          the hand-set number and its note, when there is one
create or replace function public.schedule_needs(p_from date, p_to date)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare s public.staffing_settings;
        v_mgr boolean := public.is_manager();
        v_today date := public.schedule_today();
        v_show_runs constant int := 120;     -- minutes a show keeps the room going after it starts
        v_days jsonb := '[]'::jsonb;
        d date;
        v_hrs jsonb; v_open int; v_close int;
        v_events jsonb; v_paid int; v_free int;
        v_first int; v_last int; v_first_paid int; v_first_free int; v_top_sold int;
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

    select coalesce(jsonb_agg(jsonb_build_object('title', x.title, 'at', x.starts_at,
                      'time', to_char(x.local, 'FMHH12:MI AM'), 'free', x.free, 'sold', x.sold)
                      order by x.starts_at, x.title), '[]'::jsonb),
           count(*) filter (where not x.free), count(*) filter (where x.free),
           min(x.m), max(x.m), min(x.m) filter (where not x.free), min(x.m) filter (where x.free),
           coalesce(max(x.sold) filter (where not x.free), 0),
           (array_agg(x.title order by x.starts_at) filter (where not x.free))[1],
           (array_agg(x.title order by x.starts_at) filter (where x.free))[1]
      into v_events, v_paid, v_free, v_first, v_last, v_first_paid, v_first_free, v_top_sold, v_paid_title, v_free_title
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
      ) x;

    v_day := jsonb_build_object('day', d, 'open', v_hrs, 'events', v_events);

    if v_mgr and d >= v_today then
      -- The stretch of the day somebody has to be here for.
      v_from := least(v_open, v_first - s.lead_minutes);
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
          v_parts := v_parts || jsonb_build_object('why', 'show', 'people', v_x_show, 'from', v_first_paid - s.lead_minutes,
                       'title', v_paid_title, 'full', v_full);
        elsif v_x_free > 0 then
          v_parts := v_parts || jsonb_build_object('why', 'free', 'people', v_x_free, 'from', v_first_free - s.lead_minutes,
                       'title', v_free_title);
        end if;
        v_rule := v_base + greatest(v_x_show, v_x_free);
      end if;
      select * into v_set from public.staffing_days where day = d and people is not null;
      v_day := v_day || jsonb_build_object('people', coalesce(v_set.people, v_rule), 'rule_people', v_rule, 'parts', v_parts,
                 'set', case when v_set.day is null then null else
                          jsonb_build_object('people', v_set.people, 'note', v_set.note, 'by', v_set.set_by) end);
    end if;
    v_days := v_days || v_day;
  end loop;

  return jsonb_build_object('today', v_today, 'days', v_days,
           'rules', case when v_mgr then to_jsonb(s) - 'id' - 'hours' else null end);
end $$;

-- Managers: change the numbers the rules use.
create or replace function public.schedule_needs_rules(p_open int, p_show int, p_free int, p_full int, p_full_at int, p_lead int)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  if p_open is null or p_show is null or p_free is null or p_full is null or p_full_at is null or p_lead is null
     or p_open not between 0 and 9 or p_show not between 0 and 9 or p_free not between 0 and 9
     or p_full not between 0 and 9 or p_full_at not between 1 and 500 or p_lead not between 0 and 360 then
    raise exception 'One of those numbers is out of range. People are 0 to 9, tickets 1 to 500, minutes 0 to 360.'; end if;
  update public.staffing_settings
     set open_people = p_open, show_extra = p_show, free_extra = p_free, full_extra = p_full, full_at = p_full_at,
         lead_minutes = p_lead, updated_by = public.schedule_name(auth.uid()), updated_at = now()
   where id;      -- the one row there is; said out loud so Supabase's editor doesn't stop on it
end $$;

-- Managers: set one day's number by hand, or (p_people empty) go back to what
-- the rules say for it.
create or replace function public.schedule_need_set(p_day date, p_people int, p_note text default '')
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  if p_day is null then raise exception 'Which day?'; end if;
  if p_people is not null and p_people not between 0 and 40 then
    raise exception 'That number is out of range (0 to 40).'; end if;
  insert into public.staffing_days (day, people, note, set_by, set_at)
  values (p_day, p_people, case when p_people is null then '' else left(trim(coalesce(p_note, '')), 120) end,
          public.schedule_name(auth.uid()), now())
  on conflict (day) do update set people = excluded.people, note = excluded.note, set_by = excluded.set_by, set_at = now();
end $$;

revoke all on function public.schedule_needs(date, date), public.schedule_needs_rules(int, int, int, int, int, int),
  public.schedule_need_set(date, int, text) from public, anon, authenticated;
grant execute on function public.schedule_needs(date, date), public.schedule_needs_rules(int, int, int, int, int, int),
  public.schedule_need_set(date, int, text) to authenticated;

notify pgrst, 'reload schema';
