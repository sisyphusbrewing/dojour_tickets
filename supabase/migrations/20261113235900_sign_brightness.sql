-- The front bar sign was too bright (Sam, Nov 13 2026: "make it dimmer").
-- Managers set brightness (5-100 %) on /sign/review.html; the sign reads it
-- with the other settings about once a minute. Starts at 50.
alter table public.sign_settings add column if not exists brightness integer not null default 50
  check (brightness between 5 and 100);

create or replace function public.sign_config()
returns json
language sql
stable
security definer
set search_path = public
as $$ select json_build_object('seconds', seconds, 'hidden', hidden, 'brightness', brightness) from public.sign_settings where id = 1 $$;

revoke all on function public.sign_config() from public;
grant execute on function public.sign_config() to anon, authenticated;
notify pgrst, 'reload schema';
