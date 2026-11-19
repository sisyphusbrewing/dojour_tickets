-- Printed checks for comics, only on Sam's OK (Sam, Nov 18 2026: "Need
-- secure checks for printing at the taproom for comedians, can only work on
-- my approval"; he picked "printed signature" over signing each by hand).
--
-- How a check moves:
--   draft     a manager (or the pay sheet) asks for a check for an owed line
--   approved  Sam taps Approve. Only the owner login can, and the check gets
--             its number here. Nothing else can make a check approved: not a
--             manager, not the service key GitHub holds (a trigger refuses
--             any approval that didn't come through check_approve()).
--   printing  the office PC picked it up to print
--   printed   the PC says it came out; the pay line is marked paid
--   failed    the PC couldn't print it; Sam can send it again
--   void      cancelled, with a reason. A voided number is never reused.
--
-- The bank's routing and account numbers and Sam's signature are NOT here.
-- They live only on the office PC (backup/checks.ps1), which puts them on the
-- check as it prints. This database and this public repo never see them.
--
-- Nothing is ever deleted, an approved check's amount, payee and number can't
-- change, and every step is written to check_events (which can't be changed
-- either).

create table if not exists public.check_settings (
  id            boolean primary key default true check (id),
  first_number  integer not null default 10001 check (first_number > 0)
);
insert into public.check_settings (id) values (true) on conflict do nothing;

create table if not exists public.checks (
  id            uuid primary key default gen_random_uuid(),
  number        integer unique,                    -- given when Sam approves
  payout_id     uuid references public.payouts(id),
  payee_id      uuid references public.payees(id),
  pay_to        text not null check (length(trim(pay_to)) > 0),   -- legal name, else stage name
  amount        numeric(10,2) not null check (amount > 0 and amount < 100000),
  memo          text,
  stub          text,                              -- the show and dates, on the stub
  status        text not null default 'draft'
                check (status in ('draft','approved','printing','printed','failed','void')),
  check_date    date,
  drafted_by    text,
  drafted_at    timestamptz not null default now(),
  approved_by   text,
  approved_at   timestamptz,
  claimed_at    timestamptz,                       -- the PC took it to print
  printed_at    timestamptz,
  print_note    text,
  void_reason   text,
  voided_by     text,
  voided_at     timestamptz,
  alerted       text                               -- the last thing Sam was emailed about it
);
-- One live check per pay line.
create unique index if not exists checks_one_per_payout on public.checks (payout_id) where status <> 'void';

create table if not exists public.check_events (
  id        bigserial primary key,
  check_id  uuid not null references public.checks(id),
  at        timestamptz not null default now(),
  who       text,
  what      text not null,
  note      text
);
create index if not exists check_events_check on public.check_events (check_id, at);

alter table public.check_settings enable row level security;
alter table public.checks enable row level security;
alter table public.check_events enable row level security;
-- Managers can look. Nobody writes these tables directly: every change goes
-- through the functions below.
create policy "Managers read checks" on public.checks for select to authenticated using ((select public.is_manager()));
create policy "Managers read check events" on public.check_events for select to authenticated using ((select public.is_manager()));
create policy "Managers read check settings" on public.check_settings for select to authenticated using ((select public.is_manager()));
revoke all on public.checks, public.check_events, public.check_settings from anon, authenticated;
grant select on public.checks, public.check_events, public.check_settings to authenticated;

-- The guard. Runs on every insert, update and delete, whoever does it.
create or replace function public.checks_guard()
returns trigger language plpgsql set search_path = public as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Checks are never deleted. Void it instead.';
  end if;
  if tg_op = 'INSERT' then
    if new.status <> 'draft' or new.number is not null or new.approved_at is not null then
      raise exception 'A new check starts as a draft, with no number.';
    end if;
    return new;
  end if;
  -- What a check says can't change once it exists. Void it and make another.
  if new.amount is distinct from old.amount or new.pay_to is distinct from old.pay_to
     or new.payout_id is distinct from old.payout_id or new.payee_id is distinct from old.payee_id
     or new.memo is distinct from old.memo or new.stub is distinct from old.stub
     or new.drafted_at is distinct from old.drafted_at or new.drafted_by is distinct from old.drafted_by
     or (old.number is not null and new.number is distinct from old.number)
     or (old.check_date is not null and new.check_date is distinct from old.check_date)
     or (old.approved_at is not null and (new.approved_at is distinct from old.approved_at
                                           or new.approved_by is distinct from old.approved_by)) then
    raise exception 'A check can''t be changed. Void it and make a new one.';
  end if;
  if old.status = 'void' and new.status <> 'void' then
    raise exception 'A voided check stays void.';
  end if;
  -- Only Sam's tap approves a check: leaving draft (other than to void), or
  -- getting a number or an approval stamp, happens inside check_approve().
  if ((old.status = 'draft' and new.status not in ('draft','void'))
      or (old.number is null and new.number is not null)
      or (old.approved_at is null and new.approved_at is not null))
     and coalesce(current_setting('checks.approving', true), '') <> 'yes' then
    raise exception 'Only the owner approves a check.';
  end if;
  if new.status in ('approved','printing','printed','failed') and (new.number is null or new.approved_at is null) then
    raise exception 'That check was never approved.';
  end if;
  return new;
end $$;
create trigger checks_guard before insert or update or delete on public.checks
  for each row execute function public.checks_guard();

create or replace function public.check_events_guard()
returns trigger language plpgsql as $$
begin
  raise exception 'The check log is never changed.';
end $$;
create trigger check_events_guard before update or delete on public.check_events
  for each row execute function public.check_events_guard();

-- Who is doing this, for the log: the login's email, else "the system".
create or replace function public.check_who()
returns text language sql stable security definer set search_path = public, auth as $$
  select coalesce((select email from auth.users where id = auth.uid()), 'the system');
$$;

create or replace function public.check_public(c public.checks)
returns jsonb language sql stable as $$
  select to_jsonb(c) - 'alerted';
$$;

-- A draft check for an owed pay line. Managers and the service key; the
-- owner too, and the pay sheet approves it in the same tap.
create or replace function public.check_draft(p_payout uuid)
returns jsonb language plpgsql security definer set search_path = public as $$
declare l public.payouts; p public.payees; c public.checks;
begin
  if auth.uid() is not null and not public.is_manager() then
    raise exception 'Managers only.';
  end if;
  select * into l from public.payouts where id = p_payout for update;
  if l.id is null then raise exception 'No such pay line.'; end if;
  if l.status <> 'owed' then raise exception 'That line is already paid.'; end if;
  select * into c from public.checks where payout_id = p_payout and status <> 'void';
  if c.id is not null then return public.check_public(c); end if;
  select * into p from public.payees where id = l.payee_id;
  insert into public.checks (payout_id, payee_id, pay_to, amount, memo, stub, drafted_by)
  values (l.id, p.id, coalesce(nullif(trim(p.legal_name), ''), p.name), l.amount,
          left(trim(both ' ·' from concat_ws(' · ', l.show_name, nullif(l.role, 'Other'))), 60),
          concat_ws(' · ', l.show_name, l.role, nullif(l.memo, ''),
                    case when l.show_end is not null then to_char(l.show_end, 'Mon FMDD, YYYY') end),
          public.check_who())
  returning * into c;
  insert into public.check_events (check_id, who, what, note)
  values (c.id, public.check_who(), 'drafted', c.pay_to || ' $' || c.amount);
  return public.check_public(c);
end $$;

-- Sam's OK. Owner login only. Gives the check its number and today's date.
create or replace function public.check_approve(p_id uuid)
returns jsonb language plpgsql security definer set search_path = public as $$
declare c public.checks; n integer;
begin
  if auth.uid() is null or public.my_role() is distinct from 'owner' then
    raise exception 'Only the owner approves a check.';
  end if;
  select * into c from public.checks where id = p_id for update;
  if c.id is null then raise exception 'No such check.'; end if;
  if c.status <> 'draft' then raise exception 'That check is already %.', c.status; end if;
  if c.payout_id is not null and exists (select 1 from public.payouts where id = c.payout_id and status <> 'owed') then
    raise exception 'That pay line is already marked paid.';
  end if;
  lock table public.check_settings in exclusive mode;
  select greatest((select first_number from public.check_settings), coalesce(max(number) + 1, 0))
    into n from public.checks;
  perform set_config('checks.approving', 'yes', true);
  update public.checks set status = 'approved', number = n, approved_by = public.check_who(), approved_at = now(),
         check_date = (now() at time zone 'America/Chicago')::date
   where id = p_id returning * into c;
  perform set_config('checks.approving', '', true);
  insert into public.check_events (check_id, who, what, note) values (c.id, public.check_who(), 'approved', '#' || n);
  return public.check_public(c);
end $$;

-- Cancel a check. Before it goes to the printer a manager can; after that
-- only the owner (it may be a real piece of paper). A printed check that is
-- voided puts its pay line back to owed.
create or replace function public.check_void(p_id uuid, p_reason text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare c public.checks;
begin
  if auth.uid() is null or not public.is_manager() then raise exception 'Managers only.'; end if;
  if coalesce(trim(p_reason), '') = '' then raise exception 'Say why it''s void.'; end if;
  select * into c from public.checks where id = p_id for update;
  if c.id is null then raise exception 'No such check.'; end if;
  if c.status = 'void' then return public.check_public(c); end if;
  if c.status in ('printing','printed','failed') and public.my_role() is distinct from 'owner' then
    raise exception 'Only the owner voids a check that went to the printer.';
  end if;
  update public.checks set status = 'void', void_reason = left(trim(p_reason), 200),
         voided_by = public.check_who(), voided_at = now()
   where id = p_id returning * into c;
  if c.payout_id is not null and c.printed_at is not null then
    update public.payouts set status = 'owed', paid_at = null, paid_via = null, paid_by = null
     where id = c.payout_id and paid_via = 'Check #' || c.number;
  end if;
  insert into public.check_events (check_id, who, what, note) values (c.id, public.check_who(), 'voided', c.void_reason);
  return public.check_public(c);
end $$;

-- Send an approved check to the printer again, after the PC said it failed or
-- it never said it was done. Owner only, same number. (If paper did come out,
-- void it instead.)
create or replace function public.check_retry(p_id uuid)
returns jsonb language plpgsql security definer set search_path = public as $$
declare c public.checks;
begin
  if auth.uid() is null or public.my_role() is distinct from 'owner' then
    raise exception 'Only the owner sends a check to the printer again.';
  end if;
  select * into c from public.checks where id = p_id for update;
  if c.status not in ('failed','printing') then raise exception 'That check is %.', c.status; end if;
  update public.checks set status = 'approved', claimed_at = null, alerted = null where id = p_id returning * into c;
  insert into public.check_events (check_id, who, what) values (c.id, public.check_who(), 'sent to the printer again');
  return public.check_public(c);
end $$;

-- The first number for printed checks (so they don't collide with a paper
-- checkbook on the same account). Owner only, before the first check.
create or replace function public.check_first_number(p_number integer)
returns integer language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null or public.my_role() is distinct from 'owner' then raise exception 'Owner only.'; end if;
  if exists (select 1 from public.checks where number is not null) then
    raise exception 'Checks already have numbers; the next one follows the last.';
  end if;
  if p_number is null or p_number < 1 or p_number > 99999999 then raise exception 'Pick a number from 1 to 99999999.'; end if;
  update public.check_settings set first_number = p_number where id;
  return p_number;
end $$;

-- ---------------------------------------------------------------------------
-- The office PC. It proves who it is with its check-in code (the same one as
-- device_heartbeat), and only ever sees approved checks.
-- ---------------------------------------------------------------------------
create or replace function public.check_device_ok(p_device text, p_code text)
returns boolean language sql stable security definer set search_path = public, extensions as $$
  select exists (select 1 from public.device_heartbeats d
                  where d.device = p_device and d.code_sha256 <> 'unset'
                    and d.code_sha256 = encode(extensions.digest(coalesce(p_code, ''), 'sha256'), 'hex'));
$$;

create or replace function public.checks_to_print(p_device text, p_code text)
returns setof jsonb language plpgsql security definer set search_path = public as $$
declare c public.checks;
begin
  if not public.check_device_ok(p_device, p_code) then raise exception 'Unknown device.'; end if;
  for c in update public.checks set status = 'printing', claimed_at = now()
            where status = 'approved' returning * loop
    insert into public.check_events (check_id, who, what) values (c.id, p_device, 'sent to the printer');
    return next jsonb_build_object('id', c.id, 'number', c.number, 'date', c.check_date, 'pay_to', c.pay_to,
                                   'amount', c.amount, 'memo', c.memo, 'stub', c.stub);
  end loop;
end $$;

create or replace function public.check_printed(p_device text, p_code text, p_id uuid, p_ok boolean, p_note text default null)
returns boolean language plpgsql security definer set search_path = public as $$
declare c public.checks;
begin
  if not public.check_device_ok(p_device, p_code) then raise exception 'Unknown device.'; end if;
  select * into c from public.checks where id = p_id for update;
  if c.status is distinct from 'printing' then return false; end if;
  update public.checks set status = case when p_ok then 'printed' else 'failed' end,
         printed_at = case when p_ok then now() end, print_note = left(p_note, 300)
   where id = p_id returning * into c;
  if p_ok and c.payout_id is not null then
    update public.payouts set status = 'paid', paid_at = now(), paid_via = 'Check #' || c.number, paid_by = p_device
     where id = c.payout_id and status = 'owed';
  end if;
  insert into public.check_events (check_id, who, what, note)
  values (c.id, p_device, case when p_ok then 'printed' else 'did not print' end, left(p_note, 300));
  return true;
end $$;

-- What to email Sam about, each said once (schedule_notify.py asks every few
-- minutes):
--   waiting  a draft has sat for 3 minutes without his OK
--   printed  it came out of the printer
--   failed   the PC couldn't print it
--   stuck    sent to the PC 10 minutes ago and it never said it was done
create or replace function public.check_alerts()
returns table (id uuid, number integer, pay_to text, amount numeric, state text, note text)
language plpgsql security definer set search_path = public as $$
#variable_conflict use_column
begin
  return query update public.checks c set alerted = 'waiting'
    where c.status = 'draft' and c.alerted is null and c.drafted_at < now() - interval '3 minutes'
    returning c.id, c.number, c.pay_to, c.amount, 'waiting'::text, c.stub;
  return query update public.checks c set alerted = c.status
    where c.status in ('printed','failed') and c.alerted is distinct from c.status
    returning c.id, c.number, c.pay_to, c.amount, c.status, c.print_note;
  return query update public.checks c set alerted = 'stuck'
    where c.status = 'printing' and c.alerted is distinct from 'stuck' and c.claimed_at < now() - interval '10 minutes'
    returning c.id, c.number, c.pay_to, c.amount, 'stuck'::text, c.print_note;
end $$;

revoke all on function public.checks_guard(), public.check_events_guard(), public.check_who(), public.check_public(public.checks),
  public.check_draft(uuid), public.check_approve(uuid), public.check_void(uuid, text), public.check_retry(uuid),
  public.check_first_number(integer), public.check_device_ok(text, text), public.checks_to_print(text, text),
  public.check_printed(text, text, uuid, boolean, text), public.check_alerts() from public, anon, authenticated;
grant execute on function public.check_draft(uuid) to authenticated, service_role;
grant execute on function public.check_approve(uuid), public.check_void(uuid, text), public.check_retry(uuid),
  public.check_first_number(integer) to authenticated;
grant execute on function public.checks_to_print(text, text), public.check_printed(text, text, uuid, boolean, text) to anon, authenticated;
grant execute on function public.check_alerts() to service_role;
