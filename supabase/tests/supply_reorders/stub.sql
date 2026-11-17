-- The two helpers the reorder rules lean on that the schedule's stand-in
-- (../staff_schedule/stub.sql) doesn't have. Same definitions as the real
-- database (20261026220000_role_tiers.sql and the older set_updated_at).
create or replace function public.is_owner() returns boolean language sql stable security definer set search_path = public as $$
  select public.role_rank(public.my_role()) >= 4 and auth.uid() is not null; $$;
create or replace function public.set_updated_at() returns trigger language plpgsql as $$
begin new.updated_at := now(); return new; end $$;
