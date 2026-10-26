-- Four kinds of login, each one a step up from the last:
--   door    - tonight's check-in, nothing else
--   staff   - door plus the staff tools (supplies sheet)
--   manager - everything except the owner's things below
--   owner   - Sam: comic pay and W-9s, CSS scores, sales history, and the
--             only one who can make managers and owners
-- No row in staff_roles still means door. is_manager() stays true for owners,
-- so every existing "Managers only" policy keeps working for Sam.

alter table public.staff_roles drop constraint if exists staff_roles_role_check;
alter table public.staff_roles add constraint staff_roles_role_check
  check (role in ('door', 'staff', 'manager', 'owner'));

create or replace function public.role_rank(p_role text)
returns int language sql immutable set search_path = public as $$
  select case p_role when 'owner' then 4 when 'manager' then 3 when 'staff' then 2 else 1 end;
$$;

create or replace function public.my_role()
returns text language sql stable security definer set search_path = public as $$
  select case when auth.uid() is null then null
              else coalesce((select role from public.staff_roles where user_id = auth.uid()), 'door') end;
$$;

create or replace function public.is_staff()
returns boolean language sql stable security definer set search_path = public as $$
  select public.role_rank(public.my_role()) >= 2 and auth.uid() is not null;
$$;

create or replace function public.is_manager()
returns boolean language sql stable security definer set search_path = public as $$
  select public.role_rank(public.my_role()) >= 3 and auth.uid() is not null;
$$;

create or replace function public.is_owner()
returns boolean language sql stable security definer set search_path = public as $$
  select public.role_rank(public.my_role()) >= 4 and auth.uid() is not null;
$$;

revoke all on function public.role_rank(text), public.is_staff(), public.is_owner() from public, anon;
grant execute on function public.role_rank(text), public.is_staff(), public.is_owner() to authenticated;

-- Sam's login is the owner.
update public.staff_roles set role = 'owner', updated_at = now()
 where user_id = (select id from auth.users where email = 'ticketing@sisyphusbrewing.com');

-- Staff tools: the supplies sheet opens to staff logins.
alter policy "Managers only" on public.supply_items
  using ((select public.is_staff())) with check ((select public.is_staff()));
alter policy "Managers only" on public.supply_items rename to "Staff only";

-- Owner only: comic pay, W-9s, CSS scores and notes, sales history.
alter policy "Managers only" on public.payees
  using ((select public.is_owner())) with check ((select public.is_owner()));
alter policy "Managers only" on public.payees rename to "Owner only";
alter policy "Managers only" on public.payouts
  using ((select public.is_owner())) with check ((select public.is_owner()));
alter policy "Managers only" on public.payouts rename to "Owner only";
alter policy "Managers only" on public.comic_scores
  using ((select public.is_owner())) with check ((select public.is_owner()));
alter policy "Managers only" on public.comic_scores rename to "Owner only";
alter policy "Managers only" on public.comic_notes
  using ((select public.is_owner())) with check ((select public.is_owner()));
alter policy "Managers only" on public.comic_notes rename to "Owner only";
alter policy "Managers only" on public.show_history using ((select public.is_owner()));
alter policy "Managers only" on public.show_history rename to "Owner only";
create policy "Owner only" on public.comic_views as restrictive for all to authenticated
  using ((select public.is_owner())) with check ((select public.is_owner()));
-- storage.objects policies can't be altered from here, so a second, stricter
-- restrictive policy sits beside "Managers only: read W-9s".
create policy "Owner only: read W-9s" on storage.objects as restrictive for select to authenticated
  using (bucket_id <> 'w9' or (select public.is_owner()));

-- Comic booking pitches were open to any login; managers book comics.
create policy "Managers only" on public.comic_feedback as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));

-- Comic pay requests are pay; the show nights list is for managers.
alter policy "Managers only" on public.pay_requests
  using ((select public.is_owner())) with check ((select public.is_owner()));
alter policy "Managers only" on public.pay_requests rename to "Owner only";
create policy "Managers only" on public.show_nights as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
