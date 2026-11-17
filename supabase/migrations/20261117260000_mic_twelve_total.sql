-- Tuesday open mic: 12 spots in all, first-timers first (Sam, Nov 17 2026:
-- "It's not first timers + 12 randoms it's 12 - First timers"). Every
-- first-timer still gets up, and the draw fills the rest of the 12. Replaces
-- mic_draw from 20261117250000_mic_first_timers.sql.

create or replace function public.mic_draw(p_date date, p_spots int default 12, p_by_hand boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_now timestamp := now() at time zone 'America/Chicago';
  v_n int;
begin
  if p_by_hand and coalesce(auth.role(), '') not in ('authenticated', 'service_role') then
    raise exception 'Staff only.';
  end if;
  p_spots := least(greatest(coalesce(p_spots, 12), 0), 60);
  -- One draw at a time per Tuesday, so two phones can't both draw.
  perform pg_advisory_xact_lock(hashtext('mic_draw'), p_date - date '2026-01-01');
  if not p_by_hand then
    if v_now < p_date + time '18:30' or p_date < v_now::date then
      return jsonb_build_object('drawn', 0, 'why', 'not draw time');
    end if;
    if exists (select 1 from public.mic_draws where mic_date = p_date) then
      return jsonb_build_object('drawn', 0, 'why', 'already drawn');
    end if;
    p_spots := 12;
  end if;
  if exists (select 1 from public.mic_signups where mic_date = p_date and status in ('drawn', 'not_drawn')) then
    return jsonb_build_object('drawn', 0, 'why', 'already drawn');
  end if;
  -- 12 spots in all. First-timers in the hat get spots first (if there are
  -- more than 12, 12 of them at random); the spots left are drawn from
  -- everyone else. Then all of them are shuffled together for the order.
  with hat as (
    select id, first_time, row_number() over (order by first_time desc, random()) as n
      from public.mic_signups where mic_date = p_date and status = 'hat'),
  ordered as (select id, row_number() over (order by random()) as n from hat where n <= p_spots)
  update public.mic_signups s set status = 'drawn', slot = 1000 + o.n::int
    from ordered o where s.id = o.id;
  update public.mic_signups set status = 'not_drawn', slot = null
   where mic_date = p_date and status = 'hat';
  insert into public.mic_draws (mic_date, spots, how)
    values (p_date, p_spots, case when p_by_hand then 'by hand' else 'auto' end)
    on conflict (mic_date) do update set spots = excluded.spots, how = excluded.how, drawn_at = now();
  perform public.mic_renumber(p_date);
  select count(*) into v_n from public.mic_signups where mic_date = p_date and status = 'drawn';
  return jsonb_build_object('drawn', v_n);
end $$;
