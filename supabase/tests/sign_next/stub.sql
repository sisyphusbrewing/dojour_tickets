-- Just enough of sign_art for sign_next, on a plain Postgres.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end $$;
create table public.sign_art (
  id bigserial primary key, kind text not null default 'suggestion', prompt text, from_name text,
  caption text, palette text[], rows text[], status text not null default 'approved', frames jsonb,
  last_shown timestamptz, created_at timestamptz not null default now());
