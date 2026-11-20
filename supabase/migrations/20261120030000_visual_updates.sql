-- "What's new" updates you can take in at a glance (Sam, Nov 19 2026: "We
-- should also make sure that the updates are visual and easy to understand
-- as well - comprehension is key").
--
-- Each update can now carry, besides its headline and one short line:
--   icon    - a small picture beside the headline (clock, calendar, door ...)
--             so people can tell what an update is about before reading it.
--   steps   - not a column: lines of the text that start with "1." "2." ...
--             are drawn as numbered steps (staff/news.js).
--   picture - a screenshot or photo: a file on the staff site ("/staff/updates/...",
--             made-up names only, the repo is public), or a photo a manager
--             adds, kept in the private "staff-updates"
--             storage folder. Only signed-in logins can see it, because a
--             screenshot of a staff page can show staff names.
-- Both are optional, so older updates look as they did.

alter table public.staff_updates
  add column if not exists icon text,
  add column if not exists picture text;

alter table public.staff_updates drop constraint if exists staff_updates_icon_check;
alter table public.staff_updates add constraint staff_updates_icon_check
  check (icon is null or icon in ('clock', 'calendar', 'door', 'deck', 'phone', 'safe', 'box', 'people', 'mic', 'money', 'star'));

-- The pictures. Private: the pages ask for a short-lived link for each one.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('staff-updates', 'staff-updates', false, 8388608, array['image/png', 'image/jpeg', 'image/webp', 'image/gif'])
on conflict (id) do nothing;

-- Any signed-in login sees the pictures; posting one goes through the
-- storage rules already in place, which let only managers upload, change or
-- delete files ("Managers only: upload" and friends).
create policy "Staff see update pictures" on storage.objects for select to authenticated
  using (bucket_id = 'staff-updates');
create policy "Managers add update pictures" on storage.objects for insert to authenticated
  with check (bucket_id = 'staff-updates' and (select public.is_manager()));
