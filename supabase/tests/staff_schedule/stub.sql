create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
create schema auth;
create table auth.users (id uuid primary key default gen_random_uuid(), email text unique);
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
grant usage on schema auth to authenticated, anon, service_role;
grant usage on schema public to authenticated, anon, service_role;
create table public.staff_roles (user_id uuid primary key references auth.users(id) on delete cascade,
  role text not null check (role in ('door','staff','manager','owner')), updated_at timestamptz not null default now());
alter table public.staff_roles enable row level security;
create or replace function public.role_rank(p_role text) returns int language sql immutable set search_path = public as $$
  select case p_role when 'owner' then 4 when 'manager' then 3 when 'staff' then 2 else 1 end; $$;
create or replace function public.my_role() returns text language sql stable security definer set search_path = public as $$
  select case when auth.uid() is null then null else coalesce((select role from public.staff_roles where user_id = auth.uid()), 'door') end; $$;
create or replace function public.is_staff() returns boolean language sql stable security definer set search_path = public as $$
  select public.role_rank(public.my_role()) >= 2 and auth.uid() is not null; $$;
create or replace function public.is_manager() returns boolean language sql stable security definer set search_path = public as $$
  select public.role_rank(public.my_role()) >= 3 and auth.uid() is not null; $$;
insert into auth.users (id, email) values
 ('00000000-0000-0000-0000-000000000001','ticketing@sisyphusbrewing.com'),
 ('00000000-0000-0000-0000-000000000002','ggeertsema@sisyphusbrewing.com'),
 ('00000000-0000-0000-0000-000000000003','dstork@sisyphusbrewing.com'),
 ('00000000-0000-0000-0000-000000000004','jwarren@sisyphusbrewing.com'),
 ('00000000-0000-0000-0000-000000000005','door@sisyphusbrewing.com');
insert into staff_roles (user_id, role) values
 ('00000000-0000-0000-0000-000000000001','owner'),('00000000-0000-0000-0000-000000000002','manager'),
 ('00000000-0000-0000-0000-000000000003','staff'),('00000000-0000-0000-0000-000000000004','staff'),
 ('00000000-0000-0000-0000-000000000005','door');
