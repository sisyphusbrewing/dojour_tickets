-- Paying comedians (payouts/index.html, a tile on the staff hub).
--
-- payees: everyone we pay. Each gets a private link (getpaid/?t=<token>)
--   where they tell us once how they want to be paid (Venmo, Zelle, PayPal,
--   Cash App, check...) and can upload a W-9. Nobody gets asked twice.
-- payouts: one line per person per run: "Abenezer Merdasa, Sam Jay run,
--   feature + host, $355". Owed until a manager taps Paid on the pay sheet,
--   which stamps it and lets payout_mail.py send the comic a receipt.
--
-- Managers only, same pair of policies as the other staff tables. The public
-- getpaid page never touches the tables: it goes through payee_get and
-- payee_save, which only work with a valid token.

create table if not exists public.payees (
  id            uuid primary key default gen_random_uuid(),
  token         text not null unique default encode(gen_random_bytes(12), 'hex'),
  name          text not null,                      -- stage name, as on the pay sheet
  email         text,
  phone         text,
  method        text check (method in ('Venmo','Zelle','PayPal','Cash App','Check','Cash','Wire / ACH')),
  handle        text,                               -- @venmo, Zelle phone/email, $cashtag, paypal.me name
  legal_name    text,                               -- who the check or wire is made out to
  w9_path       text,                               -- object path in the private "w9" bucket
  w9_at         timestamptz,
  info_at       timestamptz,                        -- when they last filled in the getpaid page
  invite_wanted_at timestamptz,                     -- a manager asked to email them the getpaid link
  invited_at    timestamptz,                        -- payout_mail.py sent it
  notes         text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create unique index if not exists payees_name_key on public.payees (lower(name));

create trigger payees_set_updated_at
  before update on public.payees
  for each row execute function public.set_updated_at();

create table if not exists public.payouts (
  id               uuid primary key default gen_random_uuid(),
  payee_id         uuid not null references public.payees(id),
  show_name        text not null,                   -- "Sam Jay"
  show_end         date,                            -- last night of the run; sorts the sheet
  role             text not null default 'Headliner',  -- Headliner, Host, Feature, Host + feature, Other
  amount           numeric(10,2) not null check (amount > 0),
  memo             text,                            -- what the comic sees: "Host Thu-Fri, feature Sat-Sun"
  status           text not null default 'owed' check (status in ('owed','paid')),
  paid_at          timestamptz,
  paid_via         text,                            -- method used, copied from the payee when paid
  paid_by          text,                            -- login email of whoever tapped Paid
  receipt_wanted   boolean not null default true,
  receipt_sent_at  timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index if not exists payouts_status_idx on public.payouts (status, show_end);

create trigger payouts_set_updated_at
  before update on public.payouts
  for each row execute function public.set_updated_at();

alter table public.payees enable row level security;
alter table public.payouts enable row level security;

create policy "Allow authenticated staff full access to payees"
  on public.payees for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to payees"
  on public.payees for all to service_role using (true) with check (true);
create policy "Managers only" on public.payees as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));

create policy "Allow authenticated staff full access to payouts"
  on public.payouts for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to payouts"
  on public.payouts for all to service_role using (true) with check (true);
create policy "Managers only" on public.payouts as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));

-- ---------------------------------------------------------------------------
-- The public getpaid page, by token only.
-- ---------------------------------------------------------------------------

create or replace function public.payee_public(p public.payees)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'name', p.name, 'email', p.email, 'phone', p.phone, 'method', p.method, 'handle', p.handle,
    'legal_name', p.legal_name, 'w9_on_file', p.w9_path is not null, 'info_at', p.info_at);
$$;

create or replace function public.payee_get(p_token text)
returns jsonb language sql stable security definer set search_path = public as $$
  select public.payee_public(p) from public.payees p where p.token = p_token;
$$;

create or replace function public.payee_save(p_token text, p_data jsonb, p_w9_path text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare p public.payees;
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if p_w9_path is not null and split_part(p_w9_path, '/', 1) <> p_token then
    raise exception 'That W-9 is not in your folder';
  end if;
  update public.payees set
      method     = nullif(p_data->>'method', ''),
      handle     = nullif(left(trim(p_data->>'handle'), 120), ''),
      legal_name = nullif(left(trim(p_data->>'legal_name'), 160), ''),
      email      = coalesce(nullif(left(trim(p_data->>'email'), 200), ''), email),
      phone      = coalesce(nullif(left(trim(p_data->>'phone'), 40), ''), phone),
      w9_path    = coalesce(p_w9_path, w9_path),
      w9_at      = case when p_w9_path is not null then now() else w9_at end,
      info_at    = now()
    where token = p_token
    returning * into p;
  if p.id is null then
    raise exception 'No one with that link';
  end if;
  return public.payee_public(p);
end $$;

-- Lets the storage policy check a token without reading the table.
create or replace function public.payee_token_ok(p_token text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.payees where token = p_token);
$$;

revoke all on function public.payee_get(text) from public;
revoke all on function public.payee_save(text, jsonb, text) from public;
revoke all on function public.payee_token_ok(text) from public;
grant execute on function public.payee_get(text) to anon, authenticated, service_role;
grant execute on function public.payee_save(text, jsonb, text) to anon, authenticated, service_role;
grant execute on function public.payee_token_ok(text) to anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- W-9s: private "w9" bucket. Anyone holding a valid link can upload into
-- that link's folder. Nobody but managers can read them, ever.
-- ---------------------------------------------------------------------------

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('w9', 'w9', false, 10485760,
          array['application/pdf','image/jpeg','image/png','image/webp','image/heic','image/heif'])
  on conflict (id) do nothing;

create policy "Payees upload their W-9"
  on storage.objects for insert to anon, authenticated
  with check (bucket_id = 'w9' and public.payee_token_ok((storage.foldername(name))[1]));
create policy "Managers read W-9s"
  on storage.objects for select to authenticated using (bucket_id = 'w9');
create policy "Managers only: read W-9s" on storage.objects as restrictive for select to authenticated
  using (bucket_id <> 'w9' or (select public.is_manager()));
