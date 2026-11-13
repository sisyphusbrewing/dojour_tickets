-- How long each beer or picture stays up on the front bar sign, set by a
-- manager on /sign/review.html (Sam, Nov 12 2026). One row. The sign reads it
-- about once a minute through sign_seconds().
create table if not exists public.sign_settings (
  id int primary key default 1 check (id = 1),
  seconds numeric not null default 12 check (seconds between 2 and 120),
  updated_at timestamptz not null default now()
);
insert into public.sign_settings (id) values (1) on conflict (id) do nothing;

alter table public.sign_settings enable row level security;
create policy "Managers manage sign settings" on public.sign_settings for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));

create or replace function public.sign_seconds()
returns numeric
language sql
stable
security definer
set search_path = public
as $$ select seconds from public.sign_settings where id = 1 $$;

revoke all on function public.sign_seconds() from public;
grant execute on function public.sign_seconds() to anon, authenticated;
