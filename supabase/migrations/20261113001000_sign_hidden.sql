-- Sam picks which slides the front bar sign shows (Nov 12 2026: "I want to be
-- able to control which ones we see"). hidden holds beer keys (the beer's
-- name, lowercase letters and digits only) and 'plug' for the "draw on this
-- sign" slide. Set on /sign/review.html; the sign reads sign_config() about
-- once a minute.
alter table public.sign_settings add column if not exists hidden text[] not null default '{}';

create or replace function public.sign_config()
returns json
language sql
stable
security definer
set search_path = public
as $$ select json_build_object('seconds', seconds, 'hidden', hidden) from public.sign_settings where id = 1 $$;

revoke all on function public.sign_config() from public;
grant execute on function public.sign_config() to anon, authenticated;
notify pgrst, 'reload schema';
