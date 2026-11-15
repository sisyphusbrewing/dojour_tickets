-- The Booking board (booking/index.html), built for Grace (Sam, Nov 14 2026):
-- every weekend at a glance, what each show still needs (contract, W-9, host,
-- feature, advance, emails), and the booking requests waiting for an answer.
--
-- Almost everything on the board is read from what we already keep: show
-- nights and ticket counts, comedian advances, the weekly-report contacts, the
-- pay sheet, comic scores and the tap-card pitches. Only two new tables:
--
--   booking_shows    the hand-kept part of a run: dates pencilled in before
--                    tickets exist, who is hosting and featuring, notes, and
--                    any box a manager ticked by hand.
--   booking_threads  one row per email conversation in the booking@ inbox
--                    (filed by booking_inbox.py), plus the manager's call on
--                    each request (later, pass, pencilled, booked).
--
-- Managers and the owner only. Nothing here is ever deleted from the page:
-- a pencilled date that falls through is marked "dropped".

create table if not exists public.booking_shows (
  id           uuid primary key default gen_random_uuid(),
  act          text not null,                        -- the comic or show
  first_night  date not null,
  last_night   date,
  stage        text not null default 'pencil' check (stage in ('pencil', 'confirmed', 'dropped')),
  contact      text,                                 -- who we're dealing with
  host         text,
  feature      text,
  notes        text,
  checks       jsonb not null default '{}'::jsonb,   -- boxes ticked by hand: {"contract": "yes", "w9": "na"}
  thread_key   text,                                 -- the request it came from, if any
  updated_by   text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists booking_shows_first_night_idx on public.booking_shows (first_night);

create trigger booking_shows_set_updated_at
  before update on public.booking_shows
  for each row execute function public.set_updated_at();

create table if not exists public.booking_threads (
  key          text primary key,                     -- "gm:<Gmail thread id>" or "card:<tap-card pitch id>"
  source       text not null default 'email',        -- email | card
  kind         text not null default 'other',        -- request | event | show | contract | counts
  subject      text,
  from_name    text,
  from_email   text,
  agency       text,                                 -- "UTA", "WME", ... from the sender's address
  act          text,                                 -- the comic or show it is about
  asked        text,                                 -- dates they asked about, as written
  snippet      text,                                 -- the first lines of the latest message
  docs         jsonb not null default '[]'::jsonb,   -- [{"doc": "contract", "state": "signed", "name": "...pdf", "at": "..."}]
  link         text,                                 -- opens the conversation in Gmail
  first_at     timestamptz,
  last_at      timestamptz,
  last_from    text,
  msg_count    int,
  waiting_on   text,                                 -- us | them
  status       text check (status in ('later', 'pass', 'pencil', 'booked')),   -- the manager's call; empty = new
  status_by    text,
  status_at    timestamptz,
  note         text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists booking_threads_last_at_idx on public.booking_threads (last_at desc);

create trigger booking_threads_set_updated_at
  before update on public.booking_threads
  for each row execute function public.set_updated_at();

alter table public.booking_shows enable row level security;
alter table public.booking_threads enable row level security;

create policy "Managers only" on public.booking_shows for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
create policy "Allow service_role full access to booking_shows"
  on public.booking_shows for all to service_role using (true) with check (true);
create policy "Managers only" on public.booking_threads for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
create policy "Allow service_role full access to booking_threads"
  on public.booking_threads for all to service_role using (true) with check (true);

-- Everything the board needs, in one answer. Kept as its own function with no
-- sign-in check so it can be looked at from the SQL editor; staff reach it
-- only through booking_board() below.
--
-- What it gives away from owner-only tables is deliberately thin:
--   pay sheet     how many lines are owed / paid per show, who hosted and
--                 featured, and how many payouts over $2,000 have no W-9
--                 (Sam, Nov 13 2026: over $2,000 needs a W-9). Never amounts.
--   W-9s          which names have one on file
--   comic scores  the letter grade and tickets-per-show guess, so a manager
--                 sorting requests sees what the CSS page would say (Sam gave
--                 Grace the monthly CSS review on Nov 2 2026). No stars, face
--                 or notes.
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
                   'opened', trip_at is not null, 'submitted', status = 'submitted')), '[]'::jsonb)
                   from public.advances where show_date > current_date - 30),
    'agents', (select coalesce(jsonb_agg(distinct public.show_family(show_title)), '[]'::jsonb)
                 from public.show_agents where coalesce(trim(agent_email), '') <> ''),
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

create or replace function public.booking_board()
returns jsonb language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_manager() then
    raise exception 'Managers only';
  end if;
  return public.booking_board_data();
end $$;

revoke all on function public.booking_board_data() from public, anon, authenticated;
revoke all on function public.booking_board() from public, anon;
grant execute on function public.booking_board() to authenticated;

-- Sam's own test tap of the booking card (Oct 25 2026) is filed as passed, so
-- it stays out of the "To answer" pile without the page needing a special rule.
insert into public.booking_threads (key, source, kind, act, from_name, first_at, last_at, status, status_by, status_at, note)
select 'card:' || f.id, 'card', 'request', f.name, f.name, f.created_at, f.created_at, 'pass', 'Claude', now(), 'Sam''s own test tap of the card'
  from public.comic_feedback f
 where f.data->>'kind' = 'booking' and f.name = 'Sam' and f.created_at::date = date '2026-10-25'
on conflict (key) do nothing;
