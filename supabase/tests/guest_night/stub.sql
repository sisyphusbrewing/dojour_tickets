-- Bare stand-ins for what "Your night" reads: the door list, the show
-- calendar and the door's "is this show tonight" question (the live
-- database's own, copied). Load supabase/tests/staff_schedule/stub.sql first
-- for the logins.
create table public.exchange_showtimes (
  variant_id bigint primary key, product_id bigint, show_title text, date_text text, ticket_type text,
  starts_at timestamptz, price numeric, seats_left integer, updated_at timestamptz default now());
create table public.tickets (
  unique_id text primary key, show_date text, show_title text, guest_name text, email text, tickets integer,
  checked_in_count integer default 0, checked_in boolean default false, check_in_time timestamptz,
  source text, ticket_type text, order_name text, variant_id bigint);
alter table public.tickets enable row level security;
alter table public.exchange_showtimes enable row level security;

create or replace function public.door_is_tonight(p_show_date text)
returns boolean language sql stable set search_path = public as $$
  select exists (
    select 1
    from (select (now() at time zone 'America/Chicago') as t) n,
         lateral (select (n.t)::date as d
                  union all
                  select (n.t)::date - 1 where extract(hour from n.t) < 5) days
    where p_show_date ~* (
      '^\s*(' || to_char(days.d, 'Dy') || '[a-z]*,?\s+)?' ||
      to_char(days.d, 'Mon') || '[a-z]*\.?\s+' || extract(day from days.d)::int ||
      '(,\s*' || extract(year from days.d)::int || ')?\s*(•|$)')
  );
$$;
