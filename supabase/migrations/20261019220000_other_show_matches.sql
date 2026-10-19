-- "Do I have tickets?" calls: when a name isn't on the show staff are looking
-- at, look on the same comic's other shows in case the caller has the date
-- wrong. Door logins can't read tickets directly, so this goes through a
-- function that only answers a typed search.

-- The comic behind a show title: "Advice Column - Spooky Edition",
-- "Advice Column (Late Show)" and "Advice Column" are the same family.
create or replace function public.show_family(p_title text)
returns text language sql immutable set search_path = public as $$
  select lower(trim(regexp_replace(
    regexp_replace(coalesce(p_title, ''), '\s*(\(|:|\s[-–—|]\s).*$', ''),
    '\s+', ' ', 'g')));
$$;

-- Guests matching the search on the comic's other shows. Every word typed
-- must appear in the name or email; at least 2 letters, at most 25 rows.
create or replace function public.other_show_matches(p_show_date text, p_show_title text, p_query text)
returns table (show_date text, show_title text, unique_id text, guest_name text, email text,
               tickets int, checked_in_count int, ticket_type text, source text)
language sql stable security definer set search_path = public as $$
  select t.show_date, t.show_title, t.unique_id, t.guest_name, t.email,
         t.tickets, t.checked_in_count, t.ticket_type, t.source
  from public.tickets t
  where auth.uid() is not null
    and length(trim(coalesce(p_query, ''))) >= 2
    and public.show_family(t.show_title) = public.show_family(p_show_title)
    and public.show_family(p_show_title) <> ''
    and not (t.show_date = p_show_date and t.show_title = p_show_title)
    and not exists (
      select 1 from regexp_split_to_table(lower(trim(p_query)), '\s+') w
      where position(w in lower(coalesce(t.guest_name, '') || ' ' || coalesce(t.email, ''))) = 0)
  order by t.show_date, t.guest_name
  limit 25;
$$;

revoke all on function public.show_family(text), public.other_show_matches(text, text, text) from public, anon;
grant execute on function public.show_family(text), public.other_show_matches(text, text, text) to authenticated;
