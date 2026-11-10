-- Tuesday open mic sign-up (Sam, Nov 9 2026): comics sign up online for the
-- next Tuesday mic (free, 7 PM, main taproom, from Nov 17 2026). A few spots
-- are booked ahead by staff; the rest are drawn at random from the sign-ups.
--
-- The public form (mic/index.html, embedded on sisyphusbrewing.com/pages/open-mic)
-- only goes through mic_signup(), which picks the date itself. Staff signed in
-- on mic/host.html read the list, add booked comics, and save the draw.

create table if not exists public.mic_signups (
  id          uuid primary key default gen_random_uuid(),
  mic_date    date not null,                       -- the Tuesday
  name        text not null,                       -- stage name
  email       text,                                -- blank for comics staff add by hand
  phone       text,
  first_time  boolean not null default false,
  status      text not null default 'hat'
              check (status in ('hat', 'booked', 'drawn', 'not_drawn', 'cancelled')),
  slot        int,                                 -- running order once booked or drawn
  staff_notes text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists mic_signups_date_idx on public.mic_signups (mic_date, created_at);
-- One sign-up per email per Tuesday.
create unique index if not exists mic_signups_one_per_email
  on public.mic_signups (mic_date, lower(email)) where email is not null;

create trigger mic_signups_set_updated_at
  before update on public.mic_signups
  for each row execute function public.set_updated_at();

alter table public.mic_signups enable row level security;

create policy "Allow authenticated staff full access to mic_signups"
  on public.mic_signups for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to mic_signups"
  on public.mic_signups for all to service_role using (true) with check (true);

-- Which Tuesday a sign-up made right now counts for. Sign-ups close at 5 PM
-- Central on the Tuesday itself (two hours before the mic); after that they go
-- to the next week. Nothing before the first mic, Tue Nov 17 2026.
create or replace function public.mic_next_date()
returns date language sql stable set search_path = public as $$
  with now_ct as (select (now() at time zone 'America/Chicago') as t),
       d as (select t::date as today, t::time as clock, extract(isodow from t)::int as dow from now_ct),
       cand as (
         select case
                  when dow = 2 and clock < time '17:00' then today
                  else today + ((2 - dow + 7) % 7 + case when dow = 2 then 7 else 0 end)
                end as tue
         from d)
  select greatest(tue, date '2026-11-17') from cand
$$;

grant execute on function public.mic_next_date() to anon, authenticated, service_role;

create or replace function public.mic_signup(p_name text, p_email text, p_phone text default null, p_first_time boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_date date := public.mic_next_date(); v_email text := lower(trim(coalesce(p_email, '')));
begin
  if coalesce(trim(p_name), '') = '' then
    raise exception 'We need a name to put in the hat.';
  end if;
  if v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then
    raise exception 'That email doesn''t look right.';
  end if;
  -- A bot hammering the form should not fill the hat.
  if (select count(*) from public.mic_signups where created_at > now() - interval '1 hour') >= 120 then
    raise exception 'Lots of sign-ups right now. Try again in a bit.';
  end if;
  if exists (select 1 from public.mic_signups where mic_date = v_date and lower(email) = v_email and status <> 'cancelled') then
    return jsonb_build_object('mic_date', v_date, 'already', true);
  end if;
  insert into public.mic_signups (mic_date, name, email, phone, first_time)
    values (v_date, left(trim(p_name), 80), left(v_email, 200), nullif(left(trim(coalesce(p_phone, '')), 40), ''), coalesce(p_first_time, false))
    on conflict do nothing;
  return jsonb_build_object('mic_date', v_date, 'already', false);
end $$;

revoke all on function public.mic_signup(text, text, text, boolean) from public;
grant execute on function public.mic_signup(text, text, text, boolean) to anon, authenticated, service_role;
