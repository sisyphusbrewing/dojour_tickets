-- Two kinds of staff login: door staff check guests in for tonight's shows,
-- managers do everything else (comps, reports, new shows, brewing, advances,
-- staff logins). A login with no row here is door staff, so a new login
-- starts with the least access until a manager promotes it.

create table if not exists public.staff_roles (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  role       text not null check (role in ('door', 'manager')),
  updated_at timestamptz not null default now()
);
alter table public.staff_roles enable row level security;
-- No policies: read and written only through the functions below and the
-- staff-admin edge function (service role).

-- Everyone who could sign in before this change keeps full access.
insert into public.staff_roles (user_id, role)
select id, 'manager' from auth.users
on conflict (user_id) do nothing;

create or replace function public.is_manager()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.staff_roles where user_id = auth.uid() and role = 'manager');
$$;

create or replace function public.my_role()
returns text language sql stable security definer set search_path = public as $$
  select case when auth.uid() is null then null
              when public.is_manager() then 'manager'
              else 'door' end;
$$;

-- True when a show_date string ("Sat, Oct 17 • 7:00 PM", or with ", 2027")
-- falls on tonight in Minneapolis. Until 5 AM, last night still counts, so a
-- late show doesn't vanish from the door list at midnight.
create or replace function public.door_is_tonight(p_show_date text)
returns boolean language sql stable set search_path = public as $$
  select exists (
    select 1
    from (select (now() at time zone 'America/Chicago') as t) n,
         lateral (select (n.t)::date as d
                  union all
                  select (n.t)::date - 1 where extract(hour from n.t) < 5) days
    where p_show_date ~* (
      '^\s*(' || to_char(days.d, 'Dy') || '[a-z]*,?\s+)?' ||
      to_char(days.d, 'Mon') || '[a-z]*\.?\s+' || extract(day from days.d)::int ||
      '(,\s*' || extract(year from days.d)::int || ')?\s*(•|$)')
  );
$$;

-- Tonight's shows with their counts.
create or replace function public.door_shows()
returns table (show_date text, show_title text, tickets bigint, checked_in bigint)
language sql stable security definer set search_path = public as $$
  select t.show_date, t.show_title, sum(t.tickets), sum(t.checked_in_count)
  from public.tickets t
  where auth.uid() is not null and public.door_is_tonight(t.show_date)
  group by t.show_date, t.show_title;
$$;

-- The guest list for one of tonight's shows.
create or replace function public.door_guests(p_show_date text, p_show_title text)
returns table (unique_id text, guest_name text, email text, tickets int,
               checked_in_count int, ticket_type text, source text)
language sql stable security definer set search_path = public as $$
  select t.unique_id, t.guest_name, t.email, t.tickets, t.checked_in_count, t.ticket_type, t.source
  from public.tickets t
  where auth.uid() is not null
    and t.show_date = p_show_date and t.show_title = p_show_title
    and public.door_is_tonight(t.show_date)
  order by t.guest_name;
$$;

-- Check guests in (or back out). Only tonight's tickets, and never more
-- people than the order has.
create or replace function public.door_check_in(p_unique_id text, p_count int)
returns table (unique_id text, checked_in_count int)
language sql security definer set search_path = public as $$
  update public.tickets t
     set checked_in_count = least(greatest(p_count, 0), t.tickets),
         checked_in = least(greatest(p_count, 0), t.tickets) > 0,
         check_in_time = case when p_count > 0 then now() else null end
   where auth.uid() is not null
     and t.unique_id = p_unique_id
     and public.door_is_tonight(t.show_date)
  returning t.unique_id, t.checked_in_count;
$$;

revoke all on function public.is_manager(), public.my_role(), public.door_is_tonight(text),
  public.door_shows(), public.door_guests(text, text), public.door_check_in(text, int) from public, anon;
grant execute on function public.is_manager(), public.my_role(), public.door_is_tonight(text),
  public.door_shows(), public.door_guests(text, text), public.door_check_in(text, int) to authenticated;
