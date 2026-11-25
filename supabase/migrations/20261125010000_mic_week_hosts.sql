-- "Tonight's host is: ..." on the website's Open Mic page, for the Tuesday
-- open mic and the Thursday showcase (Sam, Nov 24 2026: "We should put
-- 'Tonight's Host is:' on the Open Mic Page and same for the Showcase" and
-- "Every week it will be a different host").
--
-- The names come from mic_hosts, the week-by-week list Grace keeps on
-- /mic/hosts.html, so the page changes by itself every week and nobody types
-- a name into the website. This hands back only the date and the host's
-- name for the coming Tuesday and Thursday (today counts until 11 PM, so the
-- line stays up through the show). No links, no tokens, nothing else.

create or replace function public.mic_week_hosts()
returns jsonb language sql stable security definer set search_path = public as $$
  with now_ct as (select now() at time zone 'America/Chicago' as t),
       d as (select case when t::time >= time '23:00' then t::date + 1 else t::date end as day,
                    t::date as today from now_ct),
       nights as (
         select 2 as dow, day + ((2 - extract(isodow from day)::int + 7) % 7) as night, today from d
         union all
         select 4, day + ((4 - extract(isodow from day)::int + 7) % 7), today from d)
  select jsonb_build_object(
    'tuesday',  (select jsonb_build_object('date', n.night, 'tonight', n.night = n.today,
                        'host', nullif(trim(h.host_name), ''))
                   from nights n left join public.mic_hosts h on h.mic_date = n.night where n.dow = 2),
    'thursday', (select jsonb_build_object('date', n.night, 'tonight', n.night = n.today,
                        'host', nullif(trim(h.host_name), ''))
                   from nights n left join public.mic_hosts h on h.mic_date = n.night where n.dow = 4));
$$;
grant execute on function public.mic_week_hosts() to anon, authenticated;
