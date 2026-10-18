-- Door staff logins get tonight's guest list through the door_* functions
-- and nothing else. These restrictive policies sit on top of the existing
-- "authenticated staff" policies, so a signed-in login must also be a
-- manager to read or change the tables directly.

do $$
declare tbl text;
begin
  for tbl in
    select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity
      and c.relname not in ('staff_roles', 'menu_refresh', 'stage_timer')
  loop
    execute format('drop policy if exists "Managers only" on public.%I', tbl);
    execute format(
      'create policy "Managers only" on public.%I as restrictive for all to authenticated '
      'using ((select public.is_manager())) with check ((select public.is_manager()))', tbl);
  end loop;
end $$;

-- Storage: door logins can still see public files, but can't upload, change
-- or delete anything, and can't read job applicants' resumes.
drop policy if exists "Managers only: read resumes" on storage.objects;
create policy "Managers only: read resumes" on storage.objects as restrictive for select to authenticated
  using (bucket_id <> 'jobs' or (select public.is_manager()));
drop policy if exists "Managers only: upload" on storage.objects;
create policy "Managers only: upload" on storage.objects as restrictive for insert to authenticated
  with check ((select public.is_manager()));
drop policy if exists "Managers only: change" on storage.objects;
create policy "Managers only: change" on storage.objects as restrictive for update to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
drop policy if exists "Managers only: delete" on storage.objects;
create policy "Managers only: delete" on storage.objects as restrictive for delete to authenticated
  using ((select public.is_manager()));
