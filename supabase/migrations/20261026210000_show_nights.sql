-- Website (Shopify) show nights, saved by show_nights.py in the daily sync
-- before past showtimes are removed from Shopify. pay_shows() now merges these
-- with the Dojour nights in show_history, so a web-only night (Ali Sultan's
-- Thursday) shows up on the payme/ form too.

create table if not exists public.show_nights (
  title      text not null,
  starts_at  timestamptz not null,
  source     text not null default 'Shopify',
  created_at timestamptz not null default now(),
  primary key (title, starts_at)
);

alter table public.show_nights enable row level security;
create policy "Allow authenticated staff to read show_nights"
  on public.show_nights for select to authenticated using (true);
create policy "Allow service_role full access to show_nights"
  on public.show_nights for all to service_role using (true) with check (true);

create or replace function public.pay_shows()
returns jsonb language sql stable security definer set search_path = public as $$
  with raw as (
    select show_title t, starts_at from public.show_history
    union all
    select title, starts_at from public.show_nights
  ), nights as (
    select min(t) as show_title, (starts_at at time zone 'America/Chicago')::date d
    from raw
    where starts_at between now() - interval '60 days' and now() + interval '1 day'
      and t !~* '^cancel'
    group by lower(trim(t)), 2
  ), marked as (
    select *, case when d - lag(d) over (partition by lower(show_title) order by d) <= 4 then 0 else 1 end as new_run
    from nights
  ), runs as (
    select *, sum(new_run) over (partition by lower(show_title) order by d) as run from marked
  )
  select coalesce(jsonb_agg(jsonb_build_object('title', show_title, 'first', f, 'last', l) order by l desc, show_title), '[]'::jsonb)
  from (select min(show_title) show_title, min(d) f, max(d) l from runs group by lower(show_title), run) x;
$$;
