-- Pay requests: a public form (payme/index.html) where a comic who worked a
-- show asks Sam to Venmo them. No token needed. A request lands here, booking@
-- gets an email (pay_request_notify.yml, started by the job-applied function),
-- and it shows on the pay sheet (payouts/index.html) for a manager to approve
-- (makes or matches the payee and their owed line) or dismiss.

create table if not exists public.pay_requests (
  id           uuid primary key default gen_random_uuid(),
  show_name    text not null,
  show_dates   text,                 -- what they picked or typed, e.g. "Oct 22–24"
  show_end     date,                 -- last night of the run, when we know it
  name         text not null,
  handle       text not null,        -- Venmo username
  role         text not null,        -- Host, Feature, Opener, Headliner, Other
  amount       numeric(10,2),        -- what they were told, if they know
  email        text,
  phone        text,
  note         text,
  status       text not null default 'new' check (status in ('new','approved','dismissed')),
  payout_id    uuid references public.payouts(id) on delete set null,
  handled_by   text,
  handled_at   timestamptz,
  notified_at  timestamptz,          -- when booking@ was emailed
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists pay_requests_status_idx on public.pay_requests (status, created_at desc);

create trigger pay_requests_set_updated_at
  before update on public.pay_requests
  for each row execute function public.set_updated_at();

alter table public.pay_requests enable row level security;

create policy "Allow authenticated staff full access to pay_requests"
  on public.pay_requests for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to pay_requests"
  on public.pay_requests for all to service_role using (true) with check (true);
create policy "Managers only" on public.pay_requests as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));

-- Recent shows for the form's picker: each run (same title, nights no more
-- than 4 days apart) from the last 60 days, newest first. Titles only, no sales.
create or replace function public.pay_shows()
returns jsonb language sql stable security definer set search_path = public as $$
  with nights as (
    select distinct show_title, (starts_at at time zone 'America/Chicago')::date d
    from public.show_history
    where starts_at between now() - interval '60 days' and now() + interval '1 day'
      and show_title !~* '^cancel'
  ), marked as (
    select *, case when d - lag(d) over (partition by show_title order by d) <= 4 then 0 else 1 end as new_run
    from nights
  ), runs as (
    select *, sum(new_run) over (partition by show_title order by d) as run from marked
  )
  select coalesce(jsonb_agg(jsonb_build_object('title', show_title, 'first', f, 'last', l) order by l desc, show_title), '[]'::jsonb)
  from (select show_title, min(d) f, max(d) l from runs group by show_title, run) x;
$$;

revoke all on function public.pay_shows() from public;
grant execute on function public.pay_shows() to anon, authenticated, service_role;

create or replace function public.pay_request(p_data jsonb)
returns uuid language plpgsql security definer set search_path = public as $$
declare new_id uuid; v_amt numeric; v_end date;
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if length(p_data::text) > 4000 then
    raise exception 'That is a lot of words. Sam will read the short version.';
  end if;
  if coalesce(trim(p_data->>'name'), '') = '' then raise exception 'We need your name.'; end if;
  if coalesce(trim(p_data->>'handle'), '') = '' then raise exception 'We need your Venmo username.'; end if;
  if coalesce(trim(p_data->>'show_name'), '') = '' then raise exception 'Which show?'; end if;
  if coalesce(trim(p_data->>'role'), '') = '' then raise exception 'What did you do on the show?'; end if;
  if coalesce(trim(p_data->>'email'), '') = '' and coalesce(trim(p_data->>'phone'), '') = '' then
    raise exception 'Leave a phone or an email in case Sam has a question.';
  end if;
  begin v_amt := nullif(p_data->>'amount', '')::numeric; exception when others then v_amt := null; end;
  if v_amt is not null and (v_amt <= 0 or v_amt > 20000) then v_amt := null; end if;
  begin v_end := nullif(p_data->>'show_end', '')::date; exception when others then v_end := null; end;
  -- A bot hammering the form should not flood booking@.
  if (select count(*) from public.pay_requests where created_at > now() - interval '1 hour') >= 30 then
    raise exception 'Lots of requests right now. Try again in a bit.';
  end if;
  insert into public.pay_requests (show_name, show_dates, show_end, name, handle, role, amount, email, phone, note)
    values (left(trim(p_data->>'show_name'), 120), nullif(left(trim(p_data->>'show_dates'), 60), ''), v_end,
            left(trim(p_data->>'name'), 120), left(trim(p_data->>'handle'), 60), left(trim(p_data->>'role'), 40), v_amt,
            nullif(left(trim(p_data->>'email'), 200), ''), nullif(left(trim(p_data->>'phone'), 40), ''),
            nullif(left(trim(p_data->>'note'), 1000), ''))
    returning id into new_id;
  return new_id;
end $$;

revoke all on function public.pay_request(jsonb) from public;
grant execute on function public.pay_request(jsonb) to anon, authenticated, service_role;
