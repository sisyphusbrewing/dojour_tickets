-- A guest's picture sits as "drawing" while sign-art finishes it in the
-- background (Sam, Nov 12 2026: guests shouldn't have to wait).
alter table public.sign_art drop constraint sign_art_status_check;
alter table public.sign_art add constraint sign_art_status_check
  check (status = any (array['pending', 'approved', 'rejected', 'drawing']));
