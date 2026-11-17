-- Tuesday open mic: first-timers always get up (Sam, Nov 17 2026: "Oh the
-- first timers automatically get up and should be identified online").
--
-- At the draw every comic in the hat who ticked "This is my first time doing
-- stand-up" goes on the lineup, and 12 more are drawn at random from everyone
-- else. First-timers and drawn names are shuffled together into the blocks
-- between the guaranteed comics. The host's page and the lineup posted online
-- at 6:35 say which comics are first-timers. Replaces mic_draw,
-- mic_host_get and mic_public_lineup from 20261117240000_mic_host_picks.sql.

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
  -- Every first-timer in the hat gets up; p_spots more are drawn from the
  -- rest. Then all of them are shuffled together for the running order.
  with others as (
    select id, row_number() over (order by random()) as n
      from public.mic_signups where mic_date = p_date and status = 'hat' and not first_time),
  chosen as (
    select id from public.mic_signups where mic_date = p_date and status = 'hat' and first_time
    union all
    select id from others where n <= p_spots),
  ordered as (select id, row_number() over (order by random()) as n from chosen)
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

create or replace function public.mic_host_get(p_token text)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'mic_date', h.mic_date,
    'host_name', h.host_name,
    'open', h.mic_date >= (now() at time zone 'America/Chicago')::date,
    'drawn', exists (select 1 from public.mic_signups s where s.mic_date = h.mic_date and s.status in ('drawn', 'not_drawn')),
    'lineup', coalesce((select jsonb_agg(jsonb_build_object('name', s.name, 'first', s.first_time, 'how',
                          case when s.host_pick then 'host' when s.status = 'drawn' then 'drawn' else 'booked' end)
                          order by s.slot nulls last, s.created_at)
                         from public.mic_signups s
                        where s.mic_date = h.mic_date and s.status in ('booked', 'drawn')), '[]'::jsonb),
    'picks', coalesce((select jsonb_agg(s.name order by s.slot nulls last, s.created_at)
                         from public.mic_signups s
                        where s.mic_date = h.mic_date and s.host_pick and s.status = 'booked'), '[]'::jsonb))
  from public.mic_hosts h
  where h.token = p_token and length(coalesce(p_token, '')) >= 20
$$;
create or replace function public.mic_public_lineup()
returns jsonb language sql stable security definer set search_path = public as $$
  with n as (select (now() at time zone 'America/Chicago') as t)
  select case
    when (select t::time from n) < time '18:35' then null
    when not exists (select 1 from public.mic_signups s where s.mic_date = (select t::date from n) and s.status in ('drawn', 'not_drawn')) then null
    else jsonb_build_object(
      'mic_date', (select t::date from n),
      'host_name', (select h.host_name from public.mic_hosts h where h.mic_date = (select t::date from n)),
      'lineup', coalesce((select jsonb_agg(jsonb_build_object('name', s.name, 'first', s.first_time) order by s.slot nulls last, s.created_at)
                            from public.mic_signups s
                           where s.mic_date = (select t::date from n) and s.status in ('booked', 'drawn')), '[]'::jsonb))
  end
$$;
