-- Just enough of the real tables to check 20261120090000_close_open_signups.sql
-- (parts 1 to 3). Run after supabase/tests/staff_schedule/stub.sql.
create table public.tickets (unique_id text primary key, show_date text, show_title text, guest_name text,
  email text, tickets int, checked_in_count int default 0, checked_in boolean default false,
  check_in_time timestamptz, ticket_type text, source text);
create table public.vip_prefs (unique_id text, show_date text, show_title text, tent_name text, occasion text, seat_pref text, snack text);
create table public.mic_signups (id serial primary key, name text);
create table public.mic_hosts (id serial primary key, token text);
create table public.mic_draws (mic_date date primary key);
alter table public.mic_signups enable row level security;
alter table public.mic_hosts enable row level security;
alter table public.mic_draws enable row level security;
create policy "Allow authenticated staff full access to mic_signups" on public.mic_signups for all to authenticated using (true) with check (true);
create policy "Allow authenticated staff full access to mic_hosts" on public.mic_hosts for all to authenticated using (true) with check (true);
create policy "Allow authenticated staff to read mic_draws" on public.mic_draws for select to authenticated using (true);
grant all on all tables in schema public to anon, authenticated;
grant all on all sequences in schema public to anon, authenticated;
create function public.door_is_tonight(d text) returns boolean language sql as $$ select d = 'tonight' $$;
create function public.show_family(t text) returns text language sql as $$ select split_part(t, ' ', 1) $$;
insert into auth.users (id, email) values ('00000000-0000-0000-0000-000000000099', 'stranger@example.com');
insert into public.tickets values ('a1','tonight','Comic Show','Pat Guest','pat@example.com',2,0,false,null,'GA','Website'),
  ('a2','last week','Comic Show','Pat Guest','pat@example.com',1,0,false,null,'GA','Website');
insert into public.vip_prefs values ('a1','tonight','Comic Show','Pat','birthday','front','pretzels');
insert into public.mic_signups (name) values ('Comic One');
