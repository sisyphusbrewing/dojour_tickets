-- Tuesday open mic: online sign-ups now close at 6:30 PM Central on the
-- Tuesday (half an hour before the 7 PM mic) instead of 5 PM (Sam, Nov 16 2026).
-- Same rule otherwise: after the cutoff a sign-up counts for the next Tuesday.
create or replace function public.mic_next_date()
returns date language sql stable set search_path = public as $$
  with now_ct as (select (now() at time zone 'America/Chicago') as t),
       d as (select t::date as today, t::time as clock, extract(isodow from t)::int as dow from now_ct),
       cand as (
         select case
                  when dow = 2 and clock < time '18:30' then today
                  else today + ((2 - dow + 7) % 7 + case when dow = 2 then 7 else 0 end)
                end as tue
         from d)
  select greatest(tue, date '2026-11-17') from cand
$$;
