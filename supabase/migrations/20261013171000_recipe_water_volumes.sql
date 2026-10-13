-- Mash and sparge water volumes, as on the e-mailed recipes, plus other names a recipe goes by.
alter table public.recipes add column if not exists mash_water_gal numeric(7,1);
alter table public.recipes add column if not exists sparge_water_gal numeric(7,1);
alter table public.recipes add column if not exists aka text;
