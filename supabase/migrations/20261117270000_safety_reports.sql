-- "Say something" reports from the Green Room (Sam, Nov 17 2026: "Let's make
-- some thing for the Green Room where people can tap or go to a website if
-- they need to report unsafe behavior").
--
-- The page is safe/index.html (staff.sisyphusbrewing.com/safe/). It needs no
-- login, and a name is optional, so a report can be anonymous. Each report is
-- emailed (safety_notify.py) to the people the reporter picked: Sam and Grace,
-- only Sam, or only Grace, so someone can report about either of them.
--
-- What is NOT kept, on purpose: the phone's address on the internet, the
-- browser, or anything else that could point back to an anonymous reporter.
-- The page says so, so this must stay true.
--
-- Who can read reports: only the owner when signed in, and the service key
-- (the email job). No manager, door or staff login can, because the reporter
-- may have picked "only Sam". Nothing here is ever deleted by the page.

create table if not exists public.safety_reports (
  id            uuid primary key default gen_random_uuid(),
  what          text not null,                 -- what happened, in their words
  happened_on   date,                          -- the day it happened (null = not said)
  place         text,                          -- Green room, Stage, Bar, ...
  who           text,                          -- who was involved, if they said
  name          text,                          -- the reporter, if they said (null = anonymous)
  contact       text,                          -- a phone or email to reach them, if they left one
  send_to       text not null default 'both' check (send_to in ('both', 'sam', 'grace')),
  via           text,                          -- 'tag', 'qr' or null: how the page was opened
  notified_at   timestamptz,                   -- when the email was started
  created_at    timestamptz not null default now()
);

create index if not exists safety_reports_created_idx on public.safety_reports (created_at desc);

alter table public.safety_reports enable row level security;

-- Supabase hands anon and authenticated every right on a new table; only
-- the policies below would stand in the way. Take the rights back so a
-- report can't be read, changed or emptied from a browser.
revoke all on public.safety_reports from anon, authenticated;
grant select on public.safety_reports to authenticated;

create policy "Owner reads safety reports"
  on public.safety_reports for select to authenticated
  using ((select public.is_owner()));
create policy "Service role full access to safety_reports"
  on public.safety_reports for all to service_role using (true) with check (true);

-- The only way in from the page. Returns the new report's id, which the page
-- hands to the "job-applied" function (kind "safety") to start the email.
create or replace function public.safety_report(p_data jsonb)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  new_id uuid;
  v_what text := trim(coalesce(p_data->>'what', ''));
  v_day  date;
  v_to   text := coalesce(nullif(p_data->>'send_to', ''), 'both');
  v_via  text := nullif(p_data->>'via', '');
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if length(v_what) < 3 then
    raise exception 'Tell us a little about what happened.';
  end if;
  if length(p_data::text) > 20000 then
    raise exception 'That is too long to send in one go. Send part of it, then the rest.';
  end if;
  if v_to not in ('both', 'sam', 'grace') then
    v_to := 'both';
  end if;
  if v_via is not null and v_via not in ('tag', 'qr') then
    v_via := null;
  end if;
  begin
    v_day := nullif(p_data->>'happened_on', '')::date;
  exception when others then
    v_day := null;
  end;
  if v_day is not null and (v_day > current_date + 1 or v_day < current_date - 3650) then
    v_day := null;
  end if;
  -- A bot hammering the page should not flood anyone's inbox. Counted over
  -- everyone, since nothing about the sender is kept.
  if (select count(*) from public.safety_reports where created_at > now() - interval '1 hour') >= 20 then
    raise exception 'A lot of reports came in just now. Please tell whoever is behind the bar, or try again in a few minutes.';
  end if;
  insert into public.safety_reports (what, happened_on, place, who, name, contact, send_to, via)
    values (left(v_what, 8000), v_day,
            nullif(left(trim(coalesce(p_data->>'place', '')), 80), ''),
            nullif(left(trim(coalesce(p_data->>'who', '')), 1000), ''),
            nullif(left(trim(coalesce(p_data->>'name', '')), 120), ''),
            nullif(left(trim(coalesce(p_data->>'contact', '')), 200), ''),
            v_to, v_via)
    returning id into new_id;
  return new_id;
end $$;

revoke all on function public.safety_report(jsonb) from public;
grant execute on function public.safety_report(jsonb) to anon, authenticated, service_role;
