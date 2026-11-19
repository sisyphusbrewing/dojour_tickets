-- Office PC heartbeat and backup status (Sam, Nov 18 2026: the office PC is
-- the nightly backup and the offline fallback until a NAS arrives, and it
-- has been found asleep or off before).
--
-- The PC checks in every 10 minutes and again after each nightly backup.
-- It has no database login: it calls device_heartbeat() with a long random
-- code that lives only on the PC. The database keeps only a fingerprint of
-- that code (sha256), so this file and the database never hold the code.
--
-- device_check() is asked every few minutes by the "Schedule notices" run
-- (schedule_notify.py), which emails Sam when the PC goes quiet for 30
-- minutes, when it comes back, and when a nightly backup fails or is missed.

create table if not exists public.device_heartbeats (
  device             text primary key,
  code_sha256        text not null,                 -- fingerprint of the PC's code
  seen_at            timestamptz,
  note               text,
  last_backup_at     timestamptz,
  last_backup_ok     boolean,
  last_backup_note   text,
  offline_alerted_at timestamptz,                   -- set while "went quiet" has been sent
  backup_alerted_at  timestamptz                    -- the last backup problem we emailed about
);

alter table public.device_heartbeats enable row level security;
create policy "Managers read device status" on public.device_heartbeats
  for select to authenticated using ((select public.is_manager()));
create policy "Managers only" on public.device_heartbeats
  as restrictive for all to authenticated using ((select public.is_manager())) with check ((select public.is_manager()));
revoke all on public.device_heartbeats from anon;

-- Called by the PC (anon key + its code). p_backup_ok is null on a plain
-- check-in, true or false after a nightly backup. Returns false for a wrong code.
create or replace function public.device_heartbeat(p_device text, p_code text,
                                                   p_backup_ok boolean default null,
                                                   p_note text default null)
returns boolean language plpgsql security definer set search_path = public, extensions as $$
begin
  update public.device_heartbeats d
     set seen_at = now(),
         note = case when p_backup_ok is null then left(p_note, 500) else d.note end,
         last_backup_at   = case when p_backup_ok is null then d.last_backup_at else now() end,
         last_backup_ok   = coalesce(p_backup_ok, d.last_backup_ok),
         last_backup_note = case when p_backup_ok is null then d.last_backup_note else left(p_note, 500) end
   where d.device = p_device
     and d.code_sha256 = encode(extensions.digest(coalesce(p_code, ''), 'sha256'), 'hex');
  return found;
end $$;
revoke all on function public.device_heartbeat(text, text, boolean, text) from public;
grant execute on function public.device_heartbeat(text, text, boolean, text) to anon, authenticated;

-- What needs saying, each said once:
--   offline      no check-in for 30 minutes
--   back         checking in again after an "offline"
--   backup_failed the last nightly backup said it failed
--   backup_missed no nightly backup for 30 hours (while the PC is checking in)
create or replace function public.device_check()
returns table (device text, state text, seen_at timestamptz, last_backup_at timestamptz, note text)
language plpgsql security definer set search_path = public as $$
#variable_conflict use_column
begin
  -- One statement per kind, so a row is never changed twice at once.
  return query
    update public.device_heartbeats d set offline_alerted_at = now()
     where d.offline_alerted_at is null and d.seen_at is not null
       and d.seen_at < now() - interval '30 minutes'
    returning d.device, 'offline'::text, d.seen_at, d.last_backup_at, d.note;
  return query
    update public.device_heartbeats d set offline_alerted_at = null
     where d.offline_alerted_at is not null and d.seen_at > d.offline_alerted_at
    returning d.device, 'back'::text, d.seen_at, d.last_backup_at, d.note;
  return query
    update public.device_heartbeats d set backup_alerted_at = d.last_backup_at
     where d.last_backup_ok = false
       and d.backup_alerted_at is distinct from d.last_backup_at
    returning d.device, 'backup_failed'::text, d.seen_at, d.last_backup_at, d.last_backup_note;
  -- Missed: the PC is up but the last backup is over 30 hours old. Counted
  -- only once a first backup has run, and said at most once a day.
  return query
    update public.device_heartbeats d set backup_alerted_at = now()
     where d.seen_at > now() - interval '30 minutes'
       and d.last_backup_at is not null
       and d.last_backup_at < now() - interval '30 hours'
       and coalesce(d.backup_alerted_at, '-infinity') < now() - interval '24 hours'
       and d.last_backup_ok
    returning d.device, 'backup_missed'::text, d.seen_at, d.last_backup_at, d.last_backup_note;
end $$;
revoke all on function public.device_check() from public, anon, authenticated;
grant execute on function public.device_check() to service_role;

-- The office PC's row. Its code's fingerprint is filled in by hand when the
-- PC makes its code (never the code itself).
insert into public.device_heartbeats (device, code_sha256)
values ('office-pc', 'unset') on conflict (device) do nothing;
