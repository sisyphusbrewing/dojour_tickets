-- The advance form asks for a guest list per night of a run. It used to list
-- every day from the first night to the last, which is right for a
-- Thursday-to-Saturday comic but wrong for a show that plays Sunday,
-- Wednesday and the Sunday after: it would ask about eight nights when only
-- three have a show. (Nov 15 2026, after automatic advances started covering
-- website-only shows.)
--
-- advance_show_nights() gives the dates a show really plays between two
-- dates, read from the two live showtime lists: the website's
-- (exchange_showtimes) and Dojour's (show_history). The form's data
-- (advance_public) now carries them as "nights"; when there are none, the form
-- falls back to every day from first to last, as before.
--
-- Show dates are public (they are on the website), so anyone may call it. It
-- is security definer so it works the same from the form's own functions and
-- from a plain call.
create or replace function public.advance_show_nights(p_show text, p_act text, p_first date, p_last date)
returns jsonb language sql stable security definer set search_path = public as $f$
  select jsonb_agg(d order by d)
    from (
      select distinct (s.starts_at at time zone 'America/Chicago')::date as d
        from (select show_title, starts_at from public.exchange_showtimes
              union all
              select show_title, starts_at from public.show_history) s
       where p_first is not null
         and public.show_family(s.show_title) <> ''
         and public.show_family(s.show_title) in (public.show_family(p_show), public.show_family(p_act))
         and (s.starts_at at time zone 'America/Chicago')::date between p_first and coalesce(p_last, p_first)
    ) n;
$f$;

revoke all on function public.advance_show_nights(text, text, date, date) from public;
grant execute on function public.advance_show_nights(text, text, date, date) to anon, authenticated, service_role;

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
    'trip_at', a.trip_at,
    'nights', public.advance_show_nights(a.show_name, a.act_name, a.show_date, a.show_end_date)
  );
$f$;
