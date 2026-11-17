-- An early show brings its extra person in an hour before, not 90 minutes
-- (Sam, Nov 17 2026: "When we have a 6pm show the bartender shifts should
-- start at 5pm rather than 5:30").
--
-- Until now the extra person for a show started "lead_minutes" (90) before
-- it, whatever time it was: 5:30 for a 7 PM show, which is right, but 4:30
-- for a 6 PM one. From here on:
--   - a show or free event that starts at 6:00 PM or earlier: its extra
--     person starts 60 minutes before (5 PM for a 6 PM show, 4 PM for a 5 PM
--     one);
--   - anything later is as before: "lead_minutes" before (5:30 for 7 PM,
--     6:30 for 8 PM), the number managers can change on the Schedule.
-- The two numbers for early shows are written here, in the function, and are
-- sent to the page with the rest so the managers' box can say them. Nothing
-- else about how a day's number is worked out changes; see
-- 20261117200000_staffing_needs.sql for the whole of it.
--
-- This file only replaces the one function. No table changes.
create or replace function public.schedule_needs(p_from date, p_to date)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare s public.staffing_settings;
        v_mgr boolean := public.is_manager();
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

    v_day := jsonb_build_object('day', d, 'open', v_hrs, 'events', v_events);

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
                          jsonb_build_object('people', v_set.people, 'note', v_set.note, 'by', v_set.set_by) end);
    end if;
    v_days := v_days || v_day;
  end loop;

  return jsonb_build_object('today', v_today, 'days', v_days,
           'rules', case when v_mgr then ((to_jsonb(s) - 'id') - 'hours')
                                         || jsonb_build_object('early_at', v_early_at, 'early_lead', v_early_lead)
                         else null end);
end $$;

notify pgrst, 'reload schema';
