-- Voice notes for more than Sam (Sam, Nov 5 2026: "I want [Lindsey] to be
-- able to use the voice recorder ... for her own notes").
--
-- voice_users lists who can use /voice/, where their notes are emailed, and a
-- line about them that Claude reads before writing their notes. Each person
-- sees only their own recordings; Sam (owner) can always use it but cannot
-- see Lindsey's notes, and she can't see his.

create table if not exists public.voice_users (
  user_id uuid primary key references auth.users (id) on delete cascade,
  name text not null,
  email text not null,
  context text not null default ''
);
alter table public.voice_users enable row level security;

create policy "Read my voice settings" on public.voice_users
  for select to authenticated using (user_id = auth.uid());
create policy "Change my notes email" on public.voice_users
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create or replace function public.can_voice()
returns boolean language sql stable security definer set search_path = public as $$
  select auth.uid() is not null
     and (public.is_owner() or exists (select 1 from public.voice_users where user_id = auth.uid()));
$$;
revoke all on function public.can_voice() from public, anon;
grant execute on function public.can_voice() to authenticated;

-- Notes: your own only.
alter policy "Owner reads voice notes" on public.voice_notes
  using (public.can_voice() and created_by = auth.uid());
alter policy "Owner adds voice notes" on public.voice_notes
  with check (public.can_voice() and created_by = auth.uid());
alter policy "Owner updates voice notes" on public.voice_notes
  using (public.can_voice() and created_by = auth.uid()) with check (created_by = auth.uid());
alter policy "Owner deletes voice notes" on public.voice_notes
  using (public.can_voice() and created_by = auth.uid());

-- Audio lives under <note id>/..., so it follows the note's owner.
create or replace function public.owns_voice_note(p_name text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.voice_notes n
                 where n.id::text = split_part(p_name, '/', 1) and n.created_by = auth.uid());
$$;
revoke all on function public.owns_voice_note(text) from public, anon;
grant execute on function public.owns_voice_note(text) to authenticated;

alter policy "Owner uploads voice notes" on storage.objects
  with check (bucket_id = 'voice-notes' and public.can_voice() and public.owns_voice_note(name));
alter policy "Owner reads voice note audio" on storage.objects
  using (bucket_id = 'voice-notes' and public.owns_voice_note(name));
alter policy "Owner deletes voice note audio" on storage.objects
  using (bucket_id = 'voice-notes' and public.owns_voice_note(name));

-- Sam: notes to sam@, written with the club in mind.
insert into public.voice_users (user_id, name, email, context)
select user_id, 'Sam', 'sam@sisyphusbrewing.com',
  'Sam Harriman owns Sisyphus, a comedy club and brewery in Minneapolis. People and words that come up a lot: Grace Geertsema (taproom and comedy manager), staff Jaz Warren, Caitlin Morris, Darrin Stork, Madeline Clancy, Natalie Johnson, Morgan Ehlers; Lindsey Ziegahn (Sam''s wife); Dojour and Shopify (ticketing), GoTab (the POS), Supabase, the door app, headliner, feature, host, advance, settlement, brite tank, fermenter, kombucha, crowlers, Lagersmith.'
from public.staff_roles where role = 'owner'
on conflict (user_id) do nothing;

-- The first test note was made by the action, with no owner; it's Sam's.
update public.voice_notes set created_by = (select user_id from public.staff_roles where role = 'owner' limit 1)
where created_by is null;
