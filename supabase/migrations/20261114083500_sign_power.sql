-- An on/off switch for the front bar sign (Sam, Nov 14 2026: "turn off taproom
-- bar digital animation sign"). Off = the panels go black; the Pi keeps running
-- and checks the setting about once a minute, so switching it back on needs no
-- trip to the bar. Managers flip it on /sign/review.html.
alter table public.sign_settings add column if not exists power boolean not null default true;

create or replace function public.sign_config()
returns json
language sql
stable
security definer
set search_path = public
as $$ select json_build_object('seconds', seconds, 'hidden', hidden, 'brightness', brightness, 'on', power)
      from public.sign_settings where id = 1 $$;

revoke all on function public.sign_config() from public;
grant execute on function public.sign_config() to anon, authenticated;
notify pgrst, 'reload schema';
