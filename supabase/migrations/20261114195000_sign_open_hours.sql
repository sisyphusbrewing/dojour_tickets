-- The front bar sign follows the open hours (Sam, Nov 14 2026: "Can we have it
-- set so the sign runs during our open hours?"). Hours are from the website's
-- Visit page (Mon closed; Tue-Wed 4-9, Thu 4-11, Fri-Sat 1-11, Sun 1-6), in
-- Minneapolis time. mode: 'auto' follows the hours, 'on' and 'off' are manual
-- overrides from /sign/review.html that stay until someone sets it back to auto.
-- The Pi already asks sign_config every 30-60 s, so nothing changes on the Pi.
alter table public.sign_settings add column if not exists mode text not null default 'auto'
  check (mode in ('auto', 'on', 'off'));
alter table public.sign_settings add column if not exists hours jsonb not null default
  '{"tue":["16:00","21:00"],"wed":["16:00","21:00"],"thu":["16:00","23:00"],"fri":["13:00","23:00"],"sat":["13:00","23:00"],"sun":["13:00","18:00"]}';
update public.sign_settings set mode = case when power then 'auto' else 'off' end where id = 1;

create or replace function public.sign_open_now(h jsonb)
returns boolean
language sql
stable
set search_path = public
as $$
  select coalesce((
    select (now() at time zone 'America/Chicago')::time between (d->>0)::time and (d->>1)::time
    from (select h -> lower(to_char(now() at time zone 'America/Chicago', 'Dy')) as d) x
    where d is not null), false)
$$;

create or replace function public.sign_config()
returns json
language sql
stable
security definer
set search_path = public
as $$ select json_build_object('seconds', seconds, 'hidden', hidden, 'brightness', brightness, 'mode', mode,
        'on', case mode when 'on' then true when 'off' then false else public.sign_open_now(hours) end)
      from public.sign_settings where id = 1 $$;

revoke all on function public.sign_config() from public;
grant execute on function public.sign_config() to anon, authenticated;
notify pgrst, 'reload schema';
