-- Security audit fixes (Sam, Nov 20 2026: "Fix everything Claude can").
--
-- The problem: the database still let anyone on the internet make their own
-- login, and a login with no row in staff_roles was treated as a "door" login.
-- A door login can read tonight's guest list (names and emails), check guests
-- in, see VIP notes and change the open mic list. So a stranger could sign
-- themselves up and do all of that.
--
-- Sign-ups are being switched off in Supabase too (Authentication settings).
-- This is the second lock: a login only counts if it was made on purpose,
-- from the Manager page or staff_login.py, which always write a staff_roles
-- row. Every real login already has one (checked Nov 20 2026: 13 of 13), so
-- nobody who works here notices a thing.

-- 1. No staff_roles row = no role at all (was: "door").
create or replace function public.my_role()
returns text language sql stable security definer set search_path = public as $$
  select case when auth.uid() is null then null
              else (select role from public.staff_roles where user_id = auth.uid()) end;
$$;

-- 2. The door's calls ask "do you have a role" instead of "are you signed in".
create or replace function public.door_shows()
 returns table(show_date text, show_title text, tickets bigint, checked_in bigint)
 language sql stable security definer set search_path = public as $$
  select t.show_date, t.show_title, sum(t.tickets), sum(t.checked_in_count)
  from public.tickets t
  where public.my_role() is not null and public.door_is_tonight(t.show_date)
  group by t.show_date, t.show_title;
$$;

create or replace function public.door_guests(p_show_date text, p_show_title text)
 returns table(unique_id text, guest_name text, email text, tickets integer, checked_in_count integer, ticket_type text, source text)
 language sql stable security definer set search_path = public as $$
  select t.unique_id, t.guest_name, t.email, t.tickets, t.checked_in_count, t.ticket_type, t.source
  from public.tickets t
  where public.my_role() is not null
    and t.show_date = p_show_date and t.show_title = p_show_title
    and public.door_is_tonight(t.show_date)
  order by t.guest_name;
$$;

create or replace function public.door_check_in(p_unique_id text, p_count integer)
 returns table(unique_id text, checked_in_count integer)
 language sql security definer set search_path = public as $$
  update public.tickets t
     set checked_in_count = least(greatest(p_count, 0), t.tickets),
         checked_in = least(greatest(p_count, 0), t.tickets) > 0,
         check_in_time = case when p_count > 0 then now() else null end
   where public.my_role() is not null
     and t.unique_id = p_unique_id
     and public.door_is_tonight(t.show_date)
  returning t.unique_id, t.checked_in_count;
$$;

create or replace function public.door_vip(p_show_date text, p_show_title text)
 returns table(unique_id text, vip_tent text, vip_occasion text, vip_seat text, vip_snack text)
 language sql stable security definer set search_path = public as $$
  select p.unique_id, p.tent_name, p.occasion, p.seat_pref, p.snack
  from public.vip_prefs p
  where public.my_role() is not null and p.show_date = p_show_date and p.show_title = p_show_title;
$$;

create or replace function public.other_show_matches(p_show_date text, p_show_title text, p_query text)
 returns table(show_date text, show_title text, unique_id text, guest_name text, email text, tickets integer, checked_in_count integer, ticket_type text, source text)
 language sql stable security definer set search_path = public as $$
  select t.show_date, t.show_title, t.unique_id, t.guest_name, t.email,
         t.tickets, t.checked_in_count, t.ticket_type, t.source
  from public.tickets t
  where public.my_role() is not null
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

create or replace function public.staff_show_counts()
 returns table(show_title text, show_date text, web bigint, dojour bigint, comps bigint)
 language sql stable security definer set search_path = public as $$
  select trim(show_title)::text, trim(show_date)::text,
         coalesce(sum(coalesce(tickets, 1)) filter (where source = 'Website'), 0)::bigint,
         coalesce(sum(coalesce(tickets, 1)) filter (where source = 'Dojour' and coalesce(trim(email), '') <> ''), 0)::bigint,
         coalesce(sum(coalesce(tickets, 1)) filter (where source = 'Comp'), 0)::bigint
  from public.tickets
  where public.my_role() is not null and show_title is not null and show_date is not null
  group by 1, 2
$$;

-- 3. The open mic tables: any real login, as before, but not a stranger.
--    (alter, not drop and re-create, so the policies' names stay and the
--    Supabase SQL editor has no drop to stop on.)
alter policy "Allow authenticated staff full access to mic_signups" on public.mic_signups
  using ((select public.my_role()) is not null) with check ((select public.my_role()) is not null);
alter policy "Allow authenticated staff full access to mic_hosts" on public.mic_hosts
  using ((select public.my_role()) is not null) with check ((select public.my_role()) is not null);
alter policy "Allow authenticated staff to read mic_draws" on public.mic_draws
  using ((select public.my_role()) is not null);

-- 4. The job post closed Nov 16 2026, so the public can't upload resumes any
--    more. Resumes already there stay, readable by managers as before.
alter policy "Anyone can upload a resume" on storage.objects with check (false);

-- 5. Pin where these helpers look things up, so nothing can slip a lookalike
--    function in front of them (Supabase's own security check flags this).
alter function public.advance_public(a advances) set search_path = public, extensions;
alter function public.check_events_guard() set search_path = public, extensions;
alter function public.check_public(c checks) set search_path = public, extensions;
alter function public.clock_forgot_after() set search_path = public, extensions;
alter function public.clock_hours(p_in timestamp with time zone, p_out timestamp with time zone) set search_path = public, extensions;
alter function public.clock_period_start(p_day date) set search_path = public, extensions;
alter function public.gift_max_balance() set search_path = public, extensions;
alter function public.gift_max_load() set search_path = public, extensions;
alter function public.gift_no_rewrite() set search_path = public, extensions;
alter function public.gift_undo_window() set search_path = public, extensions;
alter function public.night_no_delete() set search_path = public, extensions;
alter function public.payee_public(p payees) set search_path = public, extensions;
alter function public.supply_items_rearm() set search_path = public, extensions;
alter function public.walkon_key(p_name text) set search_path = public, extensions;
