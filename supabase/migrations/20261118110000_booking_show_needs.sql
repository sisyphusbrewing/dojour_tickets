-- "Every show needs" on the Booking board (Sam, Nov 18 2026: "These are some
-- things we should have for every show - Manager, Do they need openers, Rider
-- requests, e-mail for sharing footage, ticket update e-mail, settlement
-- statement e-mail, how does the artist want to be paid, artist contact or
-- making sure advance gets forwarded/texted to them" and "This is just the
-- start").
--
-- The list itself lives on the page (booking/index.html, SHOW_NEEDS), so a new
-- line is one entry there. What a manager types for a run is kept here, in
-- booking_shows.info, one key per line ({"manager": "...", "openers": "We
-- book them"}). Lines that something else already knows are filled in from
-- it: the advance (who it went to, pay method, green room asks, guest sets),
-- the weekly ticket report contacts (show_agents) and where the video went
-- (recordings). Managers only, like the rest of the board.

alter table public.booking_shows add column if not exists info jsonb not null default '{}'::jsonb;

create or replace function public.booking_board_data()
returns jsonb language sql stable security definer set search_path = public as $$
  with scored as (
    select comedian, per_show, coalesce(draw_estimated, false) as estimated, coalesce(likeability, 0) as face,
           round(coalesce((points->>'draw_here')::numeric, 0) + coalesce((points->>'instagram')::numeric, 0)
               + coalesce((points->>'reddit')::numeric, 0) + coalesce((points->>'tiktok')::numeric, 0)
               + coalesce((points->>'youtube')::numeric, 0) + coalesce((points->>'momentum')::numeric, 0)
               + case when twin_cities then 10 else 0 end
               + case when coalesce(house_stars, 0) > 0 then 5 * house_stars else 12.5 end) as total
    from public.comic_scores where status = 'scored'
  ), curve as (
    -- Same bell curve as the CSS page: measured against comics who played here.
    select case when count(*) >= 10 then avg(total) else 46 end as mu,
           case when count(*) >= 10 then greatest(coalesce(stddev_pop(total), 1), 1) else 13 end as sd
    from scored where not estimated
  ), graded as (
    select s.comedian, s.per_show, s.total, s.estimated,
           substr('SABCDF', greatest(1, least(6,
             (case when (s.total - c.mu) / c.sd >= 2 then 1 when (s.total - c.mu) / c.sd >= 1.5 then 2
                   when (s.total - c.mu) / c.sd >= 0.5 then 3 when (s.total - c.mu) / c.sd >= -0.5 then 4
                   when (s.total - c.mu) / c.sd >= -1.5 then 5 else 6 end) - s.face)), 1) as grade
    from scored s cross join curve c
  )
  select jsonb_build_object(
    -- Cancelled showtimes ("CANCELED: ...") are sent too: the page uses them
    -- to take the show's old listing off the board.
    'nights', (select coalesce(jsonb_agg(jsonb_build_object('title', title, 'starts_at', starts_at) order by starts_at), '[]'::jsonb)
                 from public.show_nights
                where starts_at > now() - interval '24 days'),
    'prices', (select coalesce(jsonb_object_agg(family, price), '{}'::jsonb)
                 from (select public.show_family(show_title) as family, min(price) as price
                         from public.exchange_showtimes where price > 0 group by 1) p where family <> ''),
    'advances', (select coalesce(jsonb_agg(jsonb_build_object(
                   'id', id, 'show_name', show_name, 'act_name', act_name, 'show_date', show_date, 'show_end_date', show_end_date,
                   'has_email', coalesce(trim(contact_email), '') <> '', 'welcomed', welcome_sent_at is not null,
                   'opened', trip_at is not null, 'submitted', status = 'submitted',
                   -- For "Every show needs" (Sam, Nov 18 2026): who the advance
                   -- went to, how they want to be paid, the green room asks and
                   -- whether they bring their own openers. Never the pay handle.
                   'contact_name', contact_name, 'contact_email', contact_email,
                   'pay_method', data->>'pay_method',
                   'rider', nullif(concat_ws(' · ', nullif(data->>'gr_snacks', ''), nullif(data->>'gr_drinks', ''),
                                             nullif(data->>'gr_wish', ''), nullif(data->>'dietary', '')), ''),
                   'guest_sets', case when data->>'gs_want' = 'Yes' then coalesce(nullif(data->>'gs_who', ''), 'Yes')
                                      when data->>'gs_want' is not null then 'No' end)), '[]'::jsonb)
                   from public.advances where show_date > current_date - 30),
    'agents', (select coalesce(jsonb_agg(distinct public.show_family(show_title)), '[]'::jsonb)
                 from public.show_agents where coalesce(trim(agent_email), '') <> ''),
    -- Who gets the weekly ticket counts, per show (the "Ticket update email" line).
    'agent_emails', (select coalesce(jsonb_agg(jsonb_build_object('family', public.show_family(show_title),
                       'title', show_title, 'email', agent_email)), '[]'::jsonb)
                       from public.show_agents where coalesce(trim(agent_email), '') <> ''),
    -- Where the morning-after video went (the "Footage email" line), headliner
    -- emails only: the ones that went to booking@ to be trimmed don't count.
    'footage', (select coalesce(jsonb_agg(x), '[]'::jsonb)
                  from (select public.show_family(show_title) as family, (starts_at at time zone 'America/Chicago')::date as day,
                               max(emailed_to) as emailed_to, max(emailed_at) as emailed_at
                          from public.recordings
                         where emailed_at is not null and coalesce(emailed_to, '') !~* 'booking@'
                           and starts_at > now() - interval '60 days'
                         group by 1, 2) x),
    'w9', (select coalesce(jsonb_agg(distinct lower(trim(name))), '[]'::jsonb) from public.payees
            where w9_at is not null or coalesce(w9_path, '') <> ''),
    'pay', (select coalesce(jsonb_agg(x), '[]'::jsonb)
              from (select public.show_family(o.show_name) as family, o.show_end,
                           count(*) filter (where o.status = 'paid') as paid,
                           count(*) filter (where o.status <> 'paid') as owed,
                           coalesce(jsonb_agg(distinct p.name) filter (where o.role ~* 'host' and p.name is not null), '[]'::jsonb) as hosts,
                           coalesce(jsonb_agg(distinct p.name) filter (where o.role ~* 'feature' and p.name is not null), '[]'::jsonb) as features,
                           count(distinct o.payee_id) filter (where o.amount > 2000 and p.w9_at is null and coalesce(p.w9_path, '') = '') as w9_missing
                      from public.payouts o left join public.payees p on p.id = o.payee_id
                     where o.show_end > current_date - 60 group by 1, 2) x),
    -- Tickets sold per showtime, kept after the show has played (the tickets
    -- table drops a show once it's over). Real sales only, no holds or comps.
    'sold', (select coalesce(jsonb_agg(x), '[]'::jsonb)
               from (select show_title, show_date, sum(tickets) as tickets
                       from public.ticket_sales_daily
                      group by 1, 2 having max(sale_date) > current_date - 90) x),
    'scores', (select coalesce(jsonb_agg(jsonb_build_object('name', comedian, 'grade', grade, 'per_show', per_show,
                   'estimated', estimated, 'under', total < 35)), '[]'::jsonb) from graded),
    'cards', (select coalesce(jsonb_agg(jsonb_build_object('id', id, 'name', name, 'contact', data->>'contact',
                   'how', data->>'how', 'via', data->>'via', 'at', created_at) order by created_at desc), '[]'::jsonb)
                from public.comic_feedback
               where data->>'kind' = 'booking' and coalesce(name, '') !~* 'test|delete me|claude'),
    -- Dropped rows are sent too, so a run marked "fell through" stays off the board.
    'shows', (select coalesce(jsonb_agg(to_jsonb(s) order by first_night), '[]'::jsonb)
                from public.booking_shows s
               where coalesce(last_night, first_night) > current_date - 24),
    'threads', (select coalesce(jsonb_agg(to_jsonb(t) order by last_at desc nulls last), '[]'::jsonb)
                  from public.booking_threads t
                 where source = 'card' or coalesce(last_at, created_at) > now() - interval '180 days')
  );
$$;
