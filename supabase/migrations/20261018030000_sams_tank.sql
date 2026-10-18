-- Sam's Tank: people pitch a monthly show at Sisyphus with a two-minute video,
-- sent from tank/index.html (embedded at sisyphusbrewing.com/pages/sams-tank).
-- The public form only goes through tank_pitch(); staff (signed in, on
-- tank/review.html) and the service key read the rows. Uploaded videos go in
-- the private "tank" bucket: anyone can upload, only staff and the service
-- key can watch them.

create table if not exists public.tank_pitches (
  id           uuid primary key default gen_random_uuid(),
  show_name    text not null,
  name         text not null,
  email        text not null,
  phone        text,
  video_url    text,                                -- a link they pasted
  video_path   text,                                -- or an object path in the "tank" bucket
  data         jsonb not null default '{}'::jsonb,  -- the answers, keyed by tank/fields.js
  status       text not null default 'new' check (status in ('new','maybe','winner','pass')),
  staff_notes  text,
  notified_at  timestamptz,                         -- when booking@ was emailed
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists tank_pitches_created_idx on public.tank_pitches (created_at desc);

create trigger tank_pitches_set_updated_at
  before update on public.tank_pitches
  for each row execute function public.set_updated_at();

alter table public.tank_pitches enable row level security;

create policy "Allow authenticated staff full access to tank_pitches"
  on public.tank_pitches for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to tank_pitches"
  on public.tank_pitches for all to service_role using (true) with check (true);

create or replace function public.tank_pitch(p_data jsonb, p_video_path text default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare new_id uuid; v_url text := nullif(trim(p_data->>'video_url'), '');
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if length(p_data::text) > 20000 then
    raise exception 'That is a lot of words for a two-minute pitch.';
  end if;
  if coalesce(trim(p_data->>'name'), '') = '' or coalesce(p_data->>'email', '') !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then
    raise exception 'We need a name and a real email.';
  end if;
  if coalesce(trim(p_data->>'show_name'), '') = '' then
    raise exception 'Your show needs a name. Even a bad one.';
  end if;
  if v_url is null and p_video_path is null then
    raise exception 'The video is the whole thing. Add a link or upload one.';
  end if;
  if v_url is not null and v_url !~* '^https?://' then
    raise exception 'That video link should start with https://';
  end if;
  -- A bot hammering the form should not flood booking@.
  if (select count(*) from public.tank_pitches where created_at > now() - interval '1 hour') >= 30 then
    raise exception 'Lots of pitches right now. Try again in a bit.';
  end if;
  insert into public.tank_pitches (show_name, name, email, phone, video_url, video_path, data)
    values (left(trim(p_data->>'show_name'), 120), left(trim(p_data->>'name'), 120), left(trim(p_data->>'email'), 200),
            nullif(left(trim(p_data->>'phone'), 40), ''), left(v_url, 500), left(p_video_path, 300), p_data)
    returning id into new_id;
  return new_id;
end $$;

revoke all on function public.tank_pitch(jsonb, text) from public;
grant execute on function public.tank_pitch(jsonb, text) to anon, authenticated, service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('tank', 'tank', false, 52428800, array['video/*'])
  on conflict (id) do nothing;

create policy "Anyone can upload a tank pitch video"
  on storage.objects for insert to anon, authenticated with check (bucket_id = 'tank');
create policy "Staff watch tank pitch videos"
  on storage.objects for select to authenticated using (bucket_id = 'tank');
