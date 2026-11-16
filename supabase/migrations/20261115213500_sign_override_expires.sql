-- A manual "Always on" or "Off" on /sign/review.html now lasts only for that
-- night: the next business day (from 6 AM Minneapolis time) the sign follows
-- the open hours again by itself. Sam turned it Off at closing on Nov 14 and it
-- was still dark when the taproom opened Nov 15 ("The chalkboard sign isn't on
-- right now").
alter table public.sign_settings add column if not exists mode_set_at timestamptz not null default now();

create or replace function public.sign_mode_now(m text, set_at timestamptz)
returns text
language sql
stable
set search_path = public
as $$
  select case when m <> 'auto'
      and ((set_at at time zone 'America/Chicago') - interval '6 hours')::date
        = ((now() at time zone 'America/Chicago') - interval '6 hours')::date
    then m else 'auto' end
$$;

create or replace function public.sign_config()
returns json
language sql
stable
security definer
set search_path = public
as $$ select json_build_object('seconds', seconds, 'hidden', hidden, 'brightness', brightness,
        'mode', public.sign_mode_now(mode, mode_set_at),
        'on', case public.sign_mode_now(mode, mode_set_at) when 'on' then true when 'off' then false
              else public.sign_open_now(hours) end)
      from public.sign_settings where id = 1 $$;

revoke all on function public.sign_config() from public;
grant execute on function public.sign_config() to anon, authenticated;
notify pgrst, 'reload schema';
