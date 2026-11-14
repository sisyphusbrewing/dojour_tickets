-- Ticket counts for every show, for the "Upcoming shows" list on /staff/
-- (Sam, Nov 13 2026: staff asked to see how many tickets have sold).
-- The tickets table itself stays managers-only because it holds names and
-- emails; this returns totals only, to anyone signed in.
-- Sold = website + Dojour. Dojour rows with no buyer email are the venue's own
-- holds ("Website Hold", "Hold"), not sales, so they're left out, the same rule
-- the weekly agent reports use. Comps are counted separately.
create or replace function public.staff_show_counts()
returns table (show_title text, show_date text, web bigint, dojour bigint, comps bigint)
language sql
stable
security definer
set search_path = public
as $$
  select trim(show_title)::text, trim(show_date)::text,
         coalesce(sum(coalesce(tickets, 1)) filter (where source = 'Website'), 0)::bigint,
         coalesce(sum(coalesce(tickets, 1)) filter (where source = 'Dojour' and coalesce(trim(email), '') <> ''), 0)::bigint,
         coalesce(sum(coalesce(tickets, 1)) filter (where source = 'Comp'), 0)::bigint
  from public.tickets
  where auth.uid() is not null and show_title is not null and show_date is not null
  group by 1, 2
$$;
revoke all on function public.staff_show_counts() from public, anon;
grant execute on function public.staff_show_counts() to authenticated;
