-- Supply stock sheet for managers (supplies/index.html, a tile on the staff hub).
-- One row per thing we keep around: how many are on the shelf and the count
-- that means "order more". When on_hand drops to low_at, booking@ is emailed
-- by the "Low supplies" action (supply_notify.py), which the page starts
-- through run-workflow right after the count is saved, and which also runs
-- every morning in case one slipped through. low_alerted_at stops repeat
-- emails; it clears itself when the count goes back above low_at.
-- Managers only: same "authenticated + restrictive is_manager()" pair as the
-- other staff tables (20261018031000_manager_only.sql).

create table if not exists public.supply_items (
  id             uuid primary key default gen_random_uuid(),
  name           text not null,
  category       text not null default 'Other',
  unit           text,                       -- "sleeves", "rolls", "cases"
  on_hand        numeric(8,1) check (on_hand >= 0),   -- null until someone counts it
  low_at         numeric(8,1) not null default 1 check (low_at >= 0),
  vendor         text,
  url            text,                       -- where to buy it
  notes          text,
  sort           integer not null default 100,
  active         boolean not null default true,
  counted_by     text,                       -- login email of the last count
  counted_at     timestamptz,
  low_alerted_at timestamptz,                -- when booking@ was told it's low
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create trigger supply_items_set_updated_at
  before update on public.supply_items
  for each row execute function public.set_updated_at();

-- Restocked (or the "low at" line moved down): arm the alert again.
create or replace function public.supply_items_rearm()
returns trigger language plpgsql as $$
begin
  if new.on_hand is null or new.on_hand > new.low_at then new.low_alerted_at := null; end if;
  return new;
end $$;

create trigger supply_items_rearm
  before update on public.supply_items
  for each row execute function public.supply_items_rearm();

alter table public.supply_items enable row level security;

create policy "Allow authenticated staff full access to supply_items"
  on public.supply_items for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to supply_items"
  on public.supply_items for all to service_role using (true) with check (true);
create policy "Managers only" on public.supply_items as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));

-- A starting list, not counted yet. "Low at" numbers and vendors are guesses
-- until Sam says where he buys; managers change any of it on the page.
insert into public.supply_items (name, category, unit, low_at, vendor, url, sort)
select * from (values
  ('16 oz pint cups',        'Bar',      'sleeves', 4, 'WebstaurantStore', 'https://www.webstaurantstore.com/search/16-oz-plastic-cups.html', 10),
  ('5 oz taster cups',       'Bar',      'sleeves', 3, 'WebstaurantStore', 'https://www.webstaurantstore.com/search/5-oz-plastic-cups.html', 11),
  ('Cocktail napkins',       'Bar',      'packs',   3, 'Costco',  'https://www.costco.com/CatalogSearch?keyword=napkins', 12),
  ('Bar towels',             'Bar',      'packs',   1, 'Amazon',  'https://www.amazon.com/s?k=bar+towels', 13),
  ('CO2 tanks (full)',       'Bar',      'tanks',   1, 'Gas supplier', null, 14),
  ('Beer line cleaner',      'Bar',      'jugs',    1, 'Amazon',  'https://www.amazon.com/s?k=beer+line+cleaner', 15),
  ('Trash bags',             'Cleaning', 'boxes',   1, 'Costco',  'https://www.costco.com/CatalogSearch?keyword=trash+bags', 20),
  ('Paper towels',           'Cleaning', 'rolls',   6, 'Costco',  'https://www.costco.com/CatalogSearch?keyword=paper+towels', 21),
  ('Toilet paper',           'Cleaning', 'rolls',   12, 'Costco', 'https://www.costco.com/CatalogSearch?keyword=toilet+paper', 22),
  ('Hand soap refill',       'Cleaning', 'jugs',    1, 'Costco',  'https://www.costco.com/CatalogSearch?keyword=hand+soap+refill', 23),
  ('Sanitizer (Star San)',   'Cleaning', 'bottles', 1, 'Amazon',  'https://www.amazon.com/s?k=star+san', 24),
  ('PBW cleaner',            'Cleaning', 'tubs',    1, 'Amazon',  'https://www.amazon.com/s?k=pbw+cleaner', 25),
  ('AA batteries (mics)',    'Show',     'batteries', 8, 'Amazon', 'https://www.amazon.com/s?k=aa+batteries+48+pack', 30),
  ('Gaff tape',              'Show',     'rolls',   1, 'Amazon',  'https://www.amazon.com/s?k=gaff+tape+black', 31),
  ('Wristbands',             'Show',     'boxes',   1, 'Amazon',  'https://www.amazon.com/s?k=tyvek+wristbands', 32),
  ('Green room water',       'Show',     'cases',   1, 'Costco',  'https://www.costco.com/CatalogSearch?keyword=bottled+water', 33),
  ('Receipt paper (GoTab)',  'Office',   'rolls',   4, 'Amazon',  'https://www.amazon.com/s?k=thermal+receipt+paper+3+1%2F8', 40),
  ('Sharpies',               'Office',   'markers', 3, 'Amazon',  'https://www.amazon.com/s?k=sharpie+markers', 41)
) as v(name, category, unit, low_at, vendor, url, sort)
where not exists (select 1 from public.supply_items);
