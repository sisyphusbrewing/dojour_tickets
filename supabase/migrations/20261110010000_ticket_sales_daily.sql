-- Ticket sales by day, Dojour vs website (Sam, Nov 9 2026: "It would be good to
-- track how many are being bought each day, most of the DoJour buyers are
-- probably coming from comedians that are advertising those links rather than
-- using the Sisyphus link"). Sisyphus is phasing Dojour out, so this shows which
-- shows (and so which comics' links) still send buyers to Dojour.
--
-- tickets.purchased_at is when the order was placed: the Shopify order time, or
-- the Dojour reservation's timestamp. fetch_tickets.py fills it on every sync.
-- The tickets table drops shows once they've happened, so the daily totals are
-- copied into ticket_sales_daily, which keeps them for good.

alter table public.tickets add column if not exists purchased_at timestamptz;

create table if not exists public.ticket_sales_daily (
  sale_date date not null,          -- the day it was bought, Minneapolis time
  show_title text not null,
  show_date text not null,          -- same text as tickets.show_date, e.g. "Fri, Dec 11 • 7:00 PM"
  source text not null check (source in ('Website', 'Dojour')),
  tickets integer not null default 0,
  orders integer not null default 0,
  updated_at timestamptz not null default now(),
  primary key (sale_date, show_title, show_date, source)
);

alter table public.ticket_sales_daily enable row level security;
drop policy if exists "Managers read sales by day" on public.ticket_sales_daily;
create policy "Managers read sales by day" on public.ticket_sales_daily for select to authenticated
  using ((select public.is_manager()));

-- Rebuild the daily totals for every show still in the tickets table. Real sales
-- only: Sam's own Dojour holds and "Website Hold" rows have no email, and comps
-- aren't sales. Shows that already happened keep the totals they had.
create or replace function public.refresh_ticket_sales_daily()
returns integer
language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  create temp table _cur on commit drop as
    select (purchased_at at time zone 'America/Chicago')::date as sale_date,
           show_title::text as show_title, show_date::text as show_date, source::text as source,
           sum(coalesce(tickets, 0))::int as tickets, count(*)::int as orders
    from public.tickets
    where purchased_at is not null
      and source in ('Website', 'Dojour')
      and coalesce(email, '') <> ''
      and show_title is not null and show_date is not null
    group by 1, 2, 3, 4;

  -- A refund or cancellation takes a day's count down (or away).
  delete from public.ticket_sales_daily d
  where exists (select 1 from public.tickets t where t.show_title = d.show_title and t.show_date = d.show_date)
    and not exists (select 1 from _cur c where c.sale_date = d.sale_date and c.show_title = d.show_title
                                           and c.show_date = d.show_date and c.source = d.source);

  insert into public.ticket_sales_daily as d (sale_date, show_title, show_date, source, tickets, orders, updated_at)
    select sale_date, show_title, show_date, source, tickets, orders, now() from _cur
  on conflict (sale_date, show_title, show_date, source) do update
    set tickets = excluded.tickets, orders = excluded.orders, updated_at = now()
    where d.tickets is distinct from excluded.tickets or d.orders is distinct from excluded.orders;

  select count(*) into n from _cur;
  return n;
end $$;
revoke all on function public.refresh_ticket_sales_daily() from public, anon, authenticated;
grant execute on function public.refresh_ticket_sales_daily() to service_role;
