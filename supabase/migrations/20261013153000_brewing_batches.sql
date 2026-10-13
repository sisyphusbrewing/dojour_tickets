-- Sisyphus brewing log: beer batches, their ingredients, and a fermentation log.
-- Used by brewing/index.html (same Supabase project and staff sign-in as the door app).

create table if not exists public.batches (
  id            uuid primary key default gen_random_uuid(),
  batch_number  text,                                  -- brewer's own numbering, e.g. "26-041"
  beer_name     text not null,
  style         text,
  status        text not null default 'planned'
                check (status in ('planned','brewing','fermenting','conditioning','kegged','on_tap','finished','dumped')),
  brew_date     date,
  kegged_date   date,
  volume        numeric(8,2),                          -- how much went into the fermenter
  volume_unit   text not null default 'bbl',
  fermenter     text,                                  -- which tank
  og            numeric(5,3),
  fg            numeric(5,3),
  abv           numeric(4,2) generated always as
                (case when og is not null and fg is not null then round((og - fg) * 131.25, 2) end) stored,
  keg_count     integer,
  notes         text,
  created_by    uuid default auth.uid(),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists public.batch_ingredients (
  id          uuid primary key default gen_random_uuid(),
  batch_id    uuid not null references public.batches(id) on delete cascade,
  category    text not null default 'other'
              check (category in ('grain','hops','yeast','adjunct','water','other')),
  name        text not null,
  amount      numeric(10,3),
  unit        text,                                    -- lb, oz, g, kg, pkg, ml ...
  stage       text,                                    -- mash, boil, whirlpool, dry hop, fermenter ...
  timing      text,                                    -- "60 min", "day 4" ...
  notes       text,
  sort_order  integer not null default 0,
  created_at  timestamptz not null default now()
);

create table if not exists public.batch_log (
  id           uuid primary key default gen_random_uuid(),
  batch_id     uuid not null references public.batches(id) on delete cascade,
  logged_at    timestamptz not null default now(),
  gravity      numeric(5,3),
  temperature  numeric(5,1),
  ph           numeric(3,2),
  note         text,
  created_by   uuid default auth.uid(),
  created_at   timestamptz not null default now()
);

create index if not exists batches_brew_date_idx on public.batches (brew_date desc);
create index if not exists batches_status_idx on public.batches (status);
create index if not exists batch_ingredients_batch_idx on public.batch_ingredients (batch_id, sort_order);
create index if not exists batch_log_batch_idx on public.batch_log (batch_id, logged_at desc);

-- Keep updated_at current.
create or replace function public.set_updated_at()
returns trigger language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end $$;

create trigger batches_set_updated_at
  before update on public.batches
  for each row execute function public.set_updated_at();

-- Same access model as tickets/show_agents: signed-in staff and the service key, nobody else.
alter table public.batches enable row level security;
alter table public.batch_ingredients enable row level security;
alter table public.batch_log enable row level security;

create policy "Allow authenticated staff full access to batches"
  on public.batches for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to batches"
  on public.batches for all to service_role using (true) with check (true);

create policy "Allow authenticated staff full access to batch_ingredients"
  on public.batch_ingredients for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to batch_ingredients"
  on public.batch_ingredients for all to service_role using (true) with check (true);

create policy "Allow authenticated staff full access to batch_log"
  on public.batch_log for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to batch_log"
  on public.batch_log for all to service_role using (true) with check (true);
