-- Ticket exchanges: a customer who bought the wrong night swaps it themselves
-- at sisyphusbrewing.com/pages/exchange (exchange/index.html).
--
--   tickets.order_name / variant_id  the website order ("#4418") and the
--                     Shopify variant each door-list row came from, written by
--                     fetch_tickets.py, so a customer can find their order with
--                     its number + email
--   exchange_showtimes  every upcoming website showtime with its price and
--                     seats left, refreshed by exchange_ticket.py (each sync and
--                     after every swap); the page lists these as choices
--   ticket_exchanges  one row per swap request; the ticket-exchange edge
--                     function adds it, exchange_ticket.py does the swap in
--                     Shopify and marks it done or failed
--
-- Only the edge function (service role) touches the new tables; staff can read
-- the exchange log.

alter table public.tickets add column if not exists order_name text;
alter table public.tickets add column if not exists variant_id bigint;
create index if not exists tickets_order_name_idx on public.tickets (order_name);

create table if not exists public.exchange_showtimes (
  variant_id   bigint primary key,
  product_id   bigint not null,
  show_title   text not null,
  date_text    text not null,          -- "Fri, Nov 6 • 7:00 PM", as on the door list
  ticket_type  text,                   -- "General Admission", "VIP / Reserved Seating"
  starts_at    timestamptz not null,
  price        numeric(10,2) not null,
  seats_left   int not null,
  updated_at   timestamptz not null default now()
);

create table if not exists public.ticket_exchanges (
  id              uuid primary key default gen_random_uuid(),
  order_name      text not null,
  email           text not null,
  from_unique_id  text not null,
  from_show       text,
  to_variant_id   bigint not null,
  to_show         text,
  tickets         int,
  price_change    numeric(10,2),        -- per order: + they owe, - they keep no refund
  status          text not null default 'queued' check (status in ('queued', 'working', 'done', 'failed')),
  message         text,
  created_at      timestamptz not null default now(),
  finished_at     timestamptz
);
create index if not exists ticket_exchanges_line_idx on public.ticket_exchanges (from_unique_id);

alter table public.exchange_showtimes enable row level security;
alter table public.ticket_exchanges enable row level security;

create policy "Allow service_role full access to exchange_showtimes"
  on public.exchange_showtimes for all to service_role using (true) with check (true);
create policy "Allow service_role full access to ticket_exchanges"
  on public.ticket_exchanges for all to service_role using (true) with check (true);
create policy "Allow staff to read ticket_exchanges"
  on public.ticket_exchanges for select to authenticated using ((select public.is_manager()));

-- When a customer's order isn't on the door list yet (bought in the last few
-- hours), the edge function pulls fresh website orders, at most every 3 minutes.
create table if not exists public.exchange_state (
  id int primary key default 1 check (id = 1),
  refreshed_at timestamptz
);
insert into public.exchange_state (id) values (1) on conflict do nothing;
alter table public.exchange_state enable row level security;
create policy "Allow service_role full access to exchange_state"
  on public.exchange_state for all to service_role using (true) with check (true);
