-- Headliners name their guests on the advance (guest_count + guest_names).
-- When an advance is submitted, those guests go straight onto the door list
-- as comps, so nobody has to retype them on the manager page.
--
-- Which shows: every show of the same comic (show_family) on the advance's
-- date and the three days after it, so a Thu-Sun run is covered and the guest
-- is on the list whichever night they come.
--
-- One comp row per name, 1 ticket each ("Jane Doe +1" or "Jane Doe (+2)" adds
-- seats). If the count is higher than the names given, the rest go on one
-- "Guests of <act>" row. Re-submitting adds anyone new and updates seat
-- counts; nobody is taken off automatically (remove them on the manager page).
--
-- unique_id starts with "comp_" so the manager page can remove them and the
-- nightly sync keeps them like any other comp.

create or replace function public.advance_guest_comps()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  act    text := coalesce(nullif(trim(new.act_name), ''), new.show_name);
  want   int  := least(coalesce(nullif(regexp_replace(coalesce(new.data->>'guest_count', ''), '\D', '', 'g'), '')::int, 0), 50);
begin
  if new.status <> 'submitted' or new.show_date is null then
    return new;
  end if;

  with parts as (
    select trim(regexp_replace(p, '\(?\s*\+\s*\d+\s*\)?\s*$', '')) as name,
           1 + coalesce((regexp_match(p, '\+\s*(\d+)\s*\)?\s*$'))[1]::int, 0) as seats
      from regexp_split_to_table(coalesce(new.data->>'guest_names', ''), '[\n\r,;]+') p
  ), named as (
    select left(name, 80) as name, least(sum(seats), 50)::int as seats
      from parts where name <> '' group by left(name, 80)
  ), guests as (
    select name, seats from named
    union all
    select 'Guests of ' || act, want - (select coalesce(sum(seats), 0) from named)
     where want > (select coalesce(sum(seats), 0) from named)
  ), shows as (
    select distinct t.show_date, t.show_title
      from public.tickets t,
           generate_series(new.show_date, new.show_date + 3, interval '1 day') d
     where public.show_family(t.show_title) in (public.show_family(new.show_name), public.show_family(new.act_name))
       and public.show_family(t.show_title) <> ''
       and t.show_date ~* (
         '^\s*([a-z]+,?\s+)?' || to_char(d, 'Mon') || '[a-z]*\.?\s+' || extract(day from d)::int ||
         '(,\s*' || extract(year from d)::int || ')?\s*(•|$)')
  )
  insert into public.tickets (unique_id, show_date, show_title, guest_name, email, tickets,
                              source, checked_in, checked_in_count, check_in_time)
  select 'comp_adv_' || new.id || '_' || left(md5(lower(g.name) || '|' || s.show_date || '|' || s.show_title), 16),
         s.show_date, s.show_title, g.name, 'Comp: Guest of ' || act, g.seats,
         'Comp', false, 0, null
    from shows s cross join guests g
  on conflict (unique_id) do update
     set tickets = greatest(excluded.tickets, public.tickets.checked_in_count);

  return new;
end $$;

revoke all on function public.advance_guest_comps() from public, anon, authenticated;

create or replace trigger advances_guest_comps
  after insert or update of data, status, show_date, show_name, act_name on public.advances
  for each row execute function public.advance_guest_comps();
