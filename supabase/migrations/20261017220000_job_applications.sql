-- Sisyphus job applications: one row per applicant, sent from jobs/index.html
-- (embedded at sisyphusbrewing.com/pages/jobs). The public form only goes
-- through job_apply(); staff (signed in) and the service key read the rows.
-- Résumés go in the private "jobs" bucket: anyone can upload, only staff and
-- the service key can read them.

create table if not exists public.job_applications (
  id           uuid primary key default gen_random_uuid(),
  role         text not null default 'bartender',
  name         text not null,
  email        text not null,
  phone        text,
  data         jsonb not null default '{}'::jsonb,  -- the answers, keyed by jobs/fields.js
  resume_path  text,                                -- object path in the "jobs" bucket
  status       text not null default 'new' check (status in ('new','talking','hired','passed')),
  staff_notes  text,
  notified_at  timestamptz,                         -- when booking@ was emailed
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists job_applications_created_idx on public.job_applications (created_at desc);

create trigger job_applications_set_updated_at
  before update on public.job_applications
  for each row execute function public.set_updated_at();

alter table public.job_applications enable row level security;

create policy "Allow authenticated staff full access to job_applications"
  on public.job_applications for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to job_applications"
  on public.job_applications for all to service_role using (true) with check (true);

create or replace function public.job_apply(p_role text, p_data jsonb, p_resume_path text default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare new_id uuid;
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if length(p_data::text) > 20000 then
    raise exception 'that is a lot of words';
  end if;
  if coalesce(trim(p_data->>'name'), '') = '' or coalesce(p_data->>'email', '') !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then
    raise exception 'We need a name and a real email.';
  end if;
  -- A bot hammering the form should not flood booking@.
  if (select count(*) from public.job_applications where created_at > now() - interval '1 hour') >= 30 then
    raise exception 'Lots of applications right now. Try again in a bit.';
  end if;
  insert into public.job_applications (role, name, email, phone, data, resume_path)
    values (left(coalesce(nullif(trim(p_role), ''), 'bartender'), 40),
            left(trim(p_data->>'name'), 120), left(trim(p_data->>'email'), 200),
            nullif(left(trim(p_data->>'phone'), 40), ''), p_data, left(p_resume_path, 300))
    returning id into new_id;
  return new_id;
end $$;

revoke all on function public.job_apply(text, jsonb, text) from public;
grant execute on function public.job_apply(text, jsonb, text) to anon, authenticated, service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('jobs', 'jobs', false, 10485760,
          array['application/pdf','application/msword',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'image/jpeg','image/png','image/webp','image/heic','image/heif'])
  on conflict (id) do nothing;

create policy "Anyone can upload a resume"
  on storage.objects for insert to anon, authenticated with check (bucket_id = 'jobs');
create policy "Staff read resumes"
  on storage.objects for select to authenticated using (bucket_id = 'jobs');
