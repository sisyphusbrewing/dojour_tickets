-- Every show Dojour has ever sold, one row per showtime, so past sales can be
-- studied after the tickets table purges them (e.g. headliner following vs.
-- tickets sold). Filled by dojour_history.py ("Dojour sales history" action),
-- which upserts by Dojour instance id, so re-running only refreshes counts.
-- tickets leaves out holds (no email + "hold" in the name) and cancelled or
-- unfinished checkouts; hold_tickets keeps the holds on their own.
-- Managers only, same pair as the other staff tables.

create table if not exists public.show_history (
  instance_id   text primary key,          -- Dojour event instance id
  source        text not null default 'Dojour',
  event_title   text,                      -- raw Dojour event title
  show_title    text,                      -- cleaned (clean_show_title)
  starts_at     timestamptz,
  tickets       integer not null default 0,
  vip_tickets   integer not null default 0,
  orders        integer not null default 0,
  buyers        integer not null default 0, -- distinct buyer emails
  hold_tickets  integer not null default 0,
  revenue       numeric(10,2) not null default 0, -- ticket price only, before Dojour fees
  updated_at    timestamptz not null default now()
);

create index if not exists show_history_starts_at on public.show_history (starts_at);

alter table public.show_history enable row level security;

create policy "Allow authenticated staff to read show_history"
  on public.show_history for select to authenticated using (true);
create policy "Allow service_role full access to show_history"
  on public.show_history for all to service_role using (true) with check (true);
create policy "Managers only" on public.show_history as restrictive for select to authenticated
  using ((select public.is_manager()));
