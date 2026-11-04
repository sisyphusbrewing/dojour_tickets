-- "What's new" on the staff page (Sam, Nov 4 2026): every employee has their
-- own login, and when they sign in to /staff/ they see what changed since
-- they last looked (a new Stream Deck key, customers swapping their own
-- tickets, ...). Each person taps "Got it" and the update stops showing for
-- them. Managers post updates from the same page.

create table if not exists public.staff_updates (
  id bigint generated always as identity primary key,
  title text not null,
  body text not null default '',
  link text,                                   -- optional "Show me" page
  min_role text not null default 'door' check (min_role in ('door', 'staff', 'manager', 'owner')),
  posted_by text,
  created_at timestamptz not null default now()
);

create table if not exists public.staff_update_reads (
  update_id bigint not null references public.staff_updates (id) on delete cascade,
  user_id uuid not null default auth.uid(),
  read_at timestamptz not null default now(),
  primary key (update_id, user_id)
);

alter table public.staff_updates enable row level security;
alter table public.staff_update_reads enable row level security;

-- Everyone signed in reads the updates meant for their role; managers write.
create policy "Staff read their updates" on public.staff_updates for select to authenticated
  using (public.role_rank(public.my_role()) >= public.role_rank(min_role));
create policy "Managers post updates" on public.staff_updates for insert to authenticated
  with check ((select public.is_manager()));
create policy "Managers edit updates" on public.staff_updates for update to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
create policy "Managers remove updates" on public.staff_updates for delete to authenticated
  using ((select public.is_manager()));

-- Each login only sees and marks its own "Got it"s; managers see who read what.
create policy "Own reads" on public.staff_update_reads for select to authenticated
  using (user_id = auth.uid() or (select public.is_manager()));
create policy "Mark own read" on public.staff_update_reads for insert to authenticated
  with check (user_id = auth.uid());

-- Who has read an update, by username (managers only), for the "seen by" line.
create or replace function public.staff_update_readers(p_update bigint)
returns table (username text, read_at timestamptz)
language sql
security definer
set search_path = public, auth
as $$
  select split_part(u.email, '@', 1), r.read_at
  from public.staff_update_reads r join auth.users u on u.id = r.user_id
  where r.update_id = p_update and public.is_manager()
  order by r.read_at;
$$;
revoke all on function public.staff_update_readers(bigint) from public, anon;
grant execute on function public.staff_update_readers(bigint) to authenticated;
grant select, insert, update, delete on public.staff_updates to authenticated;
grant select, insert on public.staff_update_reads to authenticated;

insert into public.staff_updates (title, body, link, min_role, posted_by, created_at) values
('Customers can swap their own tickets',
 'Bought the wrong night? Customers can now move their tickets themselves at sisyphusbrewing.com/pages/exchange with their order number and email. It only moves to another night of the same show, at the same price or cheaper, and it closes 48 hours before either show. No refunds unless we cancel or reschedule. If they want a pricier night, they email ticketing@.',
 '../exchange/', 'door', 'Sam', '2026-10-30 18:00-05'),
('Stream Deck: new lighting buttons',
 'The BAR page now runs the whole room. PRE-SHOW: hall lights, sign, wall wash, poster lamp and shuffleboard on, house lights low. DAYTIME: everything on, house lights full. SHOW: house lights fade out, nothing else changes. ALL OFF: everything off. SUNSET is gone.',
 'stream-deck.html', 'staff', 'Sam', '2026-11-02 18:00-06'),
('Stream Deck: alarm button',
 'The ALARM key on the BAR page shows whether the alarm is set. Tap it for ARM AWAY (closing, nobody inside) or ARM HOME. There is no disarm button on the deck on purpose; use the keypad or the SimpliSafe app.',
 'stream-deck.html', 'staff', 'Sam', '2026-11-03 18:00-06');
