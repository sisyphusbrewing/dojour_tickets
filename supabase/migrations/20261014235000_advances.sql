-- Sisyphus comedian advance: one row per booked act, filled in by the comedian
-- (or their agent) through advance/index.html using a per-show link, and read
-- by booking staff in advance/booking.html.
--
-- Staff (signed in) and the service key see everything. The public form never
-- touches the table directly: it goes through the three functions below, which
-- only work with a valid token.

create table if not exists public.advances (
  id             uuid primary key default gen_random_uuid(),
  token          text not null unique default encode(gen_random_bytes(12), 'hex'),
  show_name      text not null,                       -- "Liz Miele", "Nerd Night"
  show_date      date,
  show_time      text,                                -- "7pm" or "7pm & 9:30pm"
  contact_name   text,                                -- who the link was sent to
  contact_email  text,
  act_name       text,                                -- copied from the answers on submit
  status         text not null default 'sent' check (status in ('sent','submitted')),
  data           jsonb not null default '{}'::jsonb,  -- the answers, keyed by advance/fields.js
  headshot_path  text,                                -- object path in the "advance" bucket
  staff_notes    text,
  submitted_at   timestamptz,
  notified_at    timestamptz,                         -- when booking@ was last emailed
  created_by     uuid default auth.uid(),
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists advances_show_date_idx on public.advances (show_date);

create trigger advances_set_updated_at
  before update on public.advances
  for each row execute function public.set_updated_at();

alter table public.advances enable row level security;

create policy "Allow authenticated staff full access to advances"
  on public.advances for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to advances"
  on public.advances for all to service_role using (true) with check (true);

-- ---------------------------------------------------------------------------
-- Public form access, by token only.
-- ---------------------------------------------------------------------------

-- What the form is allowed to see about an advance.
create or replace function public.advance_public(a public.advances)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'show_name', a.show_name,
    'show_date', a.show_date,
    'show_time', a.show_time,
    'contact_name', a.contact_name,
    'contact_email', a.contact_email,
    'status', a.status,
    'data', a.data,
    'headshot_path', a.headshot_path,
    'submitted_at', a.submitted_at
  );
$$;

-- Open a per-show link.
create or replace function public.advance_get(p_token text)
returns jsonb language sql stable security definer set search_path = public as $$
  select public.advance_public(a) from public.advances a where a.token = p_token;
$$;

-- "Didn't get a link?" Starts a fresh advance and returns its token.
create or replace function public.advance_open(p_show_name text, p_show_date date default null, p_show_time text default null)
returns text language plpgsql security definer set search_path = public as $$
declare t text;
begin
  if coalesce(trim(p_show_name), '') = '' then
    raise exception 'show_name is required';
  end if;
  insert into public.advances (show_name, show_date, show_time, created_by)
    values (left(trim(p_show_name), 120), p_show_date, left(p_show_time, 60), null)
    returning token into t;
  return t;
end $$;

-- Save the answers. Can be called again to update them.
create or replace function public.advance_submit(p_token text, p_data jsonb, p_headshot_path text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare a public.advances;
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if length(p_data::text) > 60000 then
    raise exception 'that is a lot of words';
  end if;
  update public.advances set
      data          = p_data,
      headshot_path = coalesce(p_headshot_path, headshot_path),
      act_name      = nullif(left(p_data->>'stage_name', 120), ''),
      contact_name  = coalesce(contact_name, nullif(left(p_data->>'stage_name', 120), '')),
      contact_email = coalesce(contact_email, nullif(left(p_data->>'email', 200), '')),
      status        = 'submitted',
      submitted_at  = now()
    where token = p_token
    returning * into a;
  if a.id is null then
    raise exception 'No advance with that link';
  end if;
  return public.advance_public(a);
end $$;

revoke all on function public.advance_get(text) from public;
revoke all on function public.advance_open(text, date, text) from public;
revoke all on function public.advance_submit(text, jsonb, text) from public;
grant execute on function public.advance_get(text) to anon, authenticated, service_role;
grant execute on function public.advance_open(text, date, text) to anon, authenticated, service_role;
grant execute on function public.advance_submit(text, jsonb, text) to anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Headshots: public bucket "advance". Anyone holding a valid token can upload
-- into that token's folder; the files are readable by link (they go on
-- posters anyway); only staff can replace or delete.
-- ---------------------------------------------------------------------------

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('advance', 'advance', true, 20971520,
          array['image/jpeg','image/png','image/webp','image/heic','image/heif','image/gif','application/pdf'])
  on conflict (id) do nothing;

create policy "Advance headshots are public"
  on storage.objects for select to public using (bucket_id = 'advance');

create policy "Upload a headshot with a valid advance token"
  on storage.objects for insert to anon, authenticated
  with check (
    bucket_id = 'advance'
    and exists (select 1 from public.advances a where a.token = (storage.foldername(name))[1])
  );

create policy "Staff manage advance files"
  on storage.objects for update to authenticated using (bucket_id = 'advance') with check (bucket_id = 'advance');
create policy "Staff delete advance files"
  on storage.objects for delete to authenticated using (bucket_id = 'advance');
