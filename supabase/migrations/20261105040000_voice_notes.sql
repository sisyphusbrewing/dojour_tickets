-- Voice notes: Sam's own Pocket-style recorder (Nov 5 2026).
-- The /voice/ page records on Sam's phone and uploads the audio in one-minute
-- pieces to the private "voice-notes" bucket under <note id>/part-NNNN.<ext>.
-- The "Voice notes" action (voice_notes.py) transcribes it, the voice-summary
-- edge function has Claude write the summary and to-dos, and sam@ gets an email.
-- Owner only: these are private conversations.

create table if not exists public.voice_notes (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  created_by uuid default auth.uid(),
  label text,                       -- what Sam typed before recording (optional)
  ext text not null default 'm4a',  -- audio container of the uploaded parts
  parts int not null default 0,     -- how many pieces were uploaded
  duration_s int,
  status text not null default 'recording'
    check (status in ('recording', 'uploaded', 'transcribing', 'summarizing', 'done', 'error')),
  error text,
  title text,
  transcript text,
  summary jsonb,
  emailed_at timestamptz,
  audio_deleted_at timestamptz
);

alter table public.voice_notes enable row level security;

drop policy if exists "Owner reads voice notes" on public.voice_notes;
create policy "Owner reads voice notes" on public.voice_notes
  for select to authenticated using (public.is_owner());
drop policy if exists "Owner adds voice notes" on public.voice_notes;
create policy "Owner adds voice notes" on public.voice_notes
  for insert to authenticated with check (public.is_owner());
drop policy if exists "Owner updates voice notes" on public.voice_notes;
create policy "Owner updates voice notes" on public.voice_notes
  for update to authenticated using (public.is_owner()) with check (public.is_owner());
drop policy if exists "Owner deletes voice notes" on public.voice_notes;
create policy "Owner deletes voice notes" on public.voice_notes
  for delete to authenticated using (public.is_owner());

insert into storage.buckets (id, name, public, file_size_limit)
values ('voice-notes', 'voice-notes', false, 52428800)
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit;

drop policy if exists "Owner uploads voice notes" on storage.objects;
create policy "Owner uploads voice notes" on storage.objects
  for insert to authenticated with check (bucket_id = 'voice-notes' and public.is_owner());
drop policy if exists "Owner reads voice note audio" on storage.objects;
create policy "Owner reads voice note audio" on storage.objects
  for select to authenticated using (bucket_id = 'voice-notes' and public.is_owner());
drop policy if exists "Owner deletes voice note audio" on storage.objects;
create policy "Owner deletes voice note audio" on storage.objects
  for delete to authenticated using (bucket_id = 'voice-notes' and public.is_owner());
