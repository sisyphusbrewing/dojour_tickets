-- Just enough of Supabase and of the tables walk-on songs read, on a plain Postgres.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;
grant usage on schema public to authenticated, anon, service_role;
create or replace function public.is_manager() returns boolean language sql stable as
  $$ select coalesce(current_setting('test.manager', true), '') = 'yes' $$;
grant execute on function public.is_manager() to anon, authenticated;
create table public.booking_shows (
  id uuid primary key default gen_random_uuid(), act text not null, first_night date not null, last_night date,
  stage text not null default 'pencil', host text, feature text, updated_at timestamptz not null default now());
create table public.advances (
  id uuid primary key default gen_random_uuid(), show_name text, act_name text, show_date date, show_end_date date,
  data jsonb not null default '{}'::jsonb, submitted_at timestamptz);
