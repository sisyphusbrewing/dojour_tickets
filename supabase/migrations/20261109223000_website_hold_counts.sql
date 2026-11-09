-- Per-show website + comp ticket totals, no names or emails. Lets the venue's own
-- computers run the Dojour hold job (dojour_holds.py) with only the public key,
-- because Dojour refuses hold requests from GitHub's servers (Sam, Nov 9 2026).
create or replace function public.website_hold_counts()
returns table(show_title text, show_date text, source text, ticket_type text, tickets bigint)
language sql stable security definer set search_path = public as $$
  select show_title::text, show_date::text, source::text, ticket_type::text, sum(coalesce(tickets,0))::bigint
  from public.tickets where source in ('Website','Comp')
  group by 1,2,3,4
$$;
revoke all on function public.website_hold_counts() from public;
grant execute on function public.website_hold_counts() to anon, authenticated, service_role;
