-- Customer drawings go straight onto the sign now (Sam, Nov 3 2026), so the
-- edge function limits how many one phone can send an hour. device is a short
-- hash of the phone's address, never the address itself.
alter table public.sign_art add column if not exists device text;
create index if not exists sign_art_device_idx on public.sign_art (device, created_at);
