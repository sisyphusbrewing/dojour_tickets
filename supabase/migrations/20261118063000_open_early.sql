-- Opening time (Sam, Nov 18 2026): "The sign should turn on 15 mins before we
-- open and the taproom should also go into daytime mode".
--
-- 1. sign_open_now() now counts the 15 minutes before opening as open, so the
--    front bar sign (sign_config, mode 'auto') lights up 15 minutes early.
--    Closing time is unchanged.
-- 2. taproom_opening() tells the office PC how many minutes ago that
--    15-minutes-early moment was today (null when we're not in open hours).
--    av/door-count/door_count.py, which already runs all day on the office PC,
--    presses the deck's DAYTIME key once when it sees a fresh opening.
create or replace function public.sign_open_now(h jsonb)
returns boolean
language sql
stable
set search_path = public
as $$
  select coalesce((
    select (now() at time zone 'America/Chicago')::time
           between (d->>0)::time - interval '15 minutes' and (d->>1)::time
    from (select h -> lower(to_char(now() at time zone 'America/Chicago', 'Dy')) as d) x
    where d is not null), false)
$$;

create or replace function public.taproom_opening()
returns json
language sql
stable
security definer
set search_path = public
as $$
  select json_build_object('minutes', (
    select floor(extract(epoch from (now() at time zone 'America/Chicago')::time
                                   - ((d->>0)::time - interval '15 minutes')) / 60)::int
    from (select hours -> lower(to_char(now() at time zone 'America/Chicago', 'Dy')) as d
          from public.sign_settings where id = 1) x
    where d is not null and public.sign_open_now(json_build_object(
      lower(to_char(now() at time zone 'America/Chicago', 'Dy')), d)::jsonb)))
$$;
revoke all on function public.taproom_opening() from public;
grant execute on function public.taproom_opening() to anon, authenticated;
notify pgrst, 'reload schema';
