-- Recipe library (the binder) and the cellar's tanks: 8 fermenters and a brite tank.
-- Used by brewing/index.html.

create table if not exists public.tanks (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique,
  kind        text not null default 'fermenter' check (kind in ('fermenter','brite')),
  capacity    numeric(8,2),
  capacity_unit text not null default 'bbl',
  sort_order  integer not null default 0,
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);

insert into public.tanks (name, kind, sort_order) values
  ('FV1','fermenter',1),('FV2','fermenter',2),('FV3','fermenter',3),('FV4','fermenter',4),
  ('FV5','fermenter',5),('FV6','fermenter',6),('FV7','fermenter',7),('FV8','fermenter',8),
  ('Brite','brite',9)
on conflict (name) do nothing;

create table if not exists public.recipes (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,
  style           text,
  batch_size      numeric(8,2),
  batch_size_unit text not null default 'bbl',
  target_og       numeric(5,3),
  target_fg       numeric(5,3),
  target_abv      numeric(4,2) generated always as
                  (case when target_og is not null and target_fg is not null then round((target_og - target_fg) * 131.25, 2) end) stored,
  ibu             numeric(5,1),
  srm             numeric(5,1),
  mash_temp       numeric(5,1),
  mash_minutes    integer,
  boil_minutes    integer,
  yeast           text,
  notes           text,
  source          text,                          -- e.g. "binder p.12", photo file name
  created_by      uuid default auth.uid(),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table if not exists public.recipe_ingredients (
  id          uuid primary key default gen_random_uuid(),
  recipe_id   uuid not null references public.recipes(id) on delete cascade,
  category    text not null default 'other'
              check (category in ('grain','hops','yeast','adjunct','water','other')),
  name        text not null,
  amount      numeric(10,3),
  unit        text,
  stage       text,
  timing      text,
  notes       text,
  sort_order  integer not null default 0,
  created_at  timestamptz not null default now()
);

create index if not exists recipes_name_idx on public.recipes (name);
create index if not exists recipe_ingredients_recipe_idx on public.recipe_ingredients (recipe_id, sort_order);

-- A batch can remember which recipe it was brewed from.
alter table public.batches add column if not exists recipe_id uuid references public.recipes(id) on delete set null;
create index if not exists batches_recipe_idx on public.batches (recipe_id);

create trigger recipes_set_updated_at
  before update on public.recipes
  for each row execute function public.set_updated_at();

alter table public.tanks enable row level security;
alter table public.recipes enable row level security;
alter table public.recipe_ingredients enable row level security;

create policy "Allow authenticated staff full access to tanks"
  on public.tanks for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to tanks"
  on public.tanks for all to service_role using (true) with check (true);

create policy "Allow authenticated staff full access to recipes"
  on public.recipes for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to recipes"
  on public.recipes for all to service_role using (true) with check (true);

create policy "Allow authenticated staff full access to recipe_ingredients"
  on public.recipe_ingredients for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to recipe_ingredients"
  on public.recipe_ingredients for all to service_role using (true) with check (true);
