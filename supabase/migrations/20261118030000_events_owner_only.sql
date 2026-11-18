-- The events@ inbox: lease and press emails are Sam's alone (Nov 18 2026).
-- The first read of events@ found other brewers writing about the lease, a
-- developer offering a building, and a reporter. Managers see everything else
-- on the Events inbox page (/inbox/); those two kinds are shown to the owner
-- login only.

alter policy "Managers read" on public.events_threads
  using ((select public.is_owner()) or ((select public.is_manager()) and kind not in ('owner', 'press')));
alter policy "Managers make the call" on public.events_threads
  using ((select public.is_owner()) or ((select public.is_manager()) and kind not in ('owner', 'press')))
  with check ((select public.is_owner()) or ((select public.is_manager()) and kind not in ('owner', 'press')));
