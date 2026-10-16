-- Grain order helper for the brewing app (brewing/index.html, Grain tab).
-- grain_plan: which recipes are coming up and how many brews of each.
-- grain_stock: pounds of each malt on hand, keyed by the app's grouped malt name.

create table if not exists public.grain_plan (
  recipe_id uuid primary key references public.recipes(id) on delete cascade,
  brews integer not null default 1 check (brews > 0),
  updated_at timestamptz not null default now()
);

create table if not exists public.grain_stock (
  malt text primary key,
  on_hand_lb numeric(8,1) not null default 0 check (on_hand_lb >= 0),
  updated_at timestamptz not null default now()
);

create trigger grain_plan_set_updated_at
  before update on public.grain_plan
  for each row execute function public.set_updated_at();
create trigger grain_stock_set_updated_at
  before update on public.grain_stock
  for each row execute function public.set_updated_at();

alter table public.grain_plan enable row level security;
alter table public.grain_stock enable row level security;

create policy "Allow authenticated staff full access to grain_plan"
  on public.grain_plan for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to grain_plan"
  on public.grain_plan for all to service_role using (true) with check (true);

create policy "Allow authenticated staff full access to grain_stock"
  on public.grain_stock for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to grain_stock"
  on public.grain_stock for all to service_role using (true) with check (true);
