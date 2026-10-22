-- Runs of shows (Ali Sultan, Thu-Sat Oct 22-24): the advance keeps the last
-- night, so the welcome email and trip ticket say "Thu–Sat, October 22–24".
alter table public.advances add column if not exists show_end_date date;

create or replace function public.advance_public(a advances) returns jsonb language sql stable as $f$
  select jsonb_build_object(
    'show_name', a.show_name,
    'show_date', a.show_date,
    'show_end_date', a.show_end_date,
    'show_time', a.show_time,
    'contact_name', a.contact_name,
    'contact_email', a.contact_email,
    'status', a.status,
    'data', a.data,
    'headshot_path', a.headshot_path,
    'submitted_at', a.submitted_at,
    'trip_at', a.trip_at
  );
$f$;

-- Guest comps, night by night. On a run the trip asks for a guest list per
-- night and saves it as data.guest_nights = [{"d": "2026-10-22", "n": 2,
-- "names": "Jane Doe\nJo Roe +1"}, ...]; each list goes only on that night's
-- shows. Without guest_nights (the one-page form, older advances) it works as
-- before: one list on every night from show_date through show_end_date, or
-- the three days after show_date when there is no end date.
create or replace function public.advance_guest_comps()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  act    text := coalesce(nullif(trim(new.act_name), ''), new.show_name);
  v_want int  := least(coalesce(nullif(regexp_replace(coalesce(new.data->>'guest_count', ''), '\D', '', 'g'), '')::int, 0), 50);
  by_night boolean := coalesce(jsonb_typeof(new.data->'guest_nights') = 'array', false);
begin
  if new.status <> 'submitted' or new.show_date is null then
    return new;
  end if;

  with nights as (
    select (e->>'d')::date as d, coalesce(e->>'names', '') as names,
           least(coalesce(nullif(regexp_replace(coalesce(e->>'n', ''), '\D', '', 'g'), '')::int, 0), 50) as want
      from jsonb_array_elements(case when by_night then new.data->'guest_nights' else '[]'::jsonb end) e
     where coalesce(e->>'d', '') ~ '^\d{4}-\d{2}-\d{2}$'
    union all
    select d::date, coalesce(new.data->>'guest_names', ''), v_want
      from generate_series(new.show_date, coalesce(new.show_end_date, new.show_date + 3), interval '1 day') d
     where not by_night
  ), parts as (
    select n.d, trim(regexp_replace(p, '\(?\s*\+\s*\d+\s*\)?\s*$', '')) as name,
           1 + coalesce((regexp_match(p, '\+\s*(\d+)\s*\)?\s*$'))[1]::int, 0) as seats
      from nights n, regexp_split_to_table(n.names, '[\n\r,;]+') p
  ), named as (
    select d, left(name, 80) as name, least(sum(seats), 50)::int as seats
      from parts where name <> '' group by d, left(name, 80)
  ), guests as (
    select d, name, seats from named
    union all
    select n.d, 'Guests of ' || act, n.want - coalesce((select sum(m.seats) from named m where m.d = n.d), 0)::int
      from nights n
     where n.want > coalesce((select sum(m.seats) from named m where m.d = n.d), 0)
  ), shows as (
    select distinct n.d, t.show_date, t.show_title
      from public.tickets t, (select distinct d from nights) n
     where public.show_family(t.show_title) in (public.show_family(new.show_name), public.show_family(new.act_name))
       and public.show_family(t.show_title) <> ''
       and t.show_date ~* (
         '^\s*([a-z]+,?\s+)?' || to_char(n.d, 'Mon') || '[a-z]*\.?\s+' || extract(day from n.d)::int ||
         '(,\s*' || extract(year from n.d)::int || ')?\s*(•|$)')
  )
  insert into public.tickets (unique_id, show_date, show_title, guest_name, email, tickets,
                              source, checked_in, checked_in_count, check_in_time)
  select 'comp_adv_' || new.id || '_' || left(md5(lower(g.name) || '|' || s.show_date || '|' || s.show_title), 16),
         s.show_date, s.show_title, g.name, 'Comp: Guest of ' || act, g.seats,
         'Comp', false, 0, null
    from shows s join guests g on g.d = s.d
  on conflict (unique_id) do update
     set tickets = greatest(excluded.tickets, public.tickets.checked_in_count);

  return new;
end $$;

revoke all on function public.advance_guest_comps() from public, anon, authenticated;

create or replace trigger advances_guest_comps
  after insert or update of data, status, show_date, show_end_date, show_name, act_name on public.advances
  for each row execute function public.advance_guest_comps();
