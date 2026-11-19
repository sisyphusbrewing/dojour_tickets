-- Just enough of the pay sheet and the office PC row for the check rules.
create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;
create table public.payees (id uuid primary key default gen_random_uuid(), name text not null, legal_name text, method text);
create table public.payouts (id uuid primary key default gen_random_uuid(), payee_id uuid not null references public.payees(id),
  show_name text not null, show_end date, role text not null default 'Headliner', amount numeric(10,2) not null, memo text,
  status text not null default 'owed', paid_at timestamptz, paid_via text, paid_by text);
create table public.device_heartbeats (device text primary key, code_sha256 text not null);
insert into public.device_heartbeats values ('office-pc', encode(extensions.digest('pc-secret', 'sha256'), 'hex'));
insert into public.payees (id, name, legal_name, method) values
 ('10000000-0000-0000-0000-000000000001', 'Nate Varrone', 'Nathan Varrone', 'Check'),
 ('10000000-0000-0000-0000-000000000002', 'Aiden Thibault', null, 'Check');
insert into public.payouts (id, payee_id, show_name, show_end, role, amount) values
 ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'Nate Varrone', current_date - 1, 'Headliner', 1920),
 ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', 'Nate Varrone', current_date - 1, 'Host', 288);
grant select on all tables in schema public to authenticated;
