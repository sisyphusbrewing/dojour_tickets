-- Tuesday open mic: women's spots go from 3 to 30% of the drawn spots, so 4
-- of 12 (Sam, Nov 17 2026: "I'm not saying we need 50/50 men to women
-- performers, but it can't be 100/0 or 90/10 men to women" / "70/30 is
-- nice!"). Still a floor, never a cap: if fewer women signed up, all of them
-- get on. Replaces mic_draw from 20261117270000_mic_women_spots.sql.

create or replace function public.mic_draw(p_date date, p_spots int default 12, p_by_hand boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_now timestamp := now() at time zone 'America/Chicago';
  v_n int;
  v_ft uuid[]; v_w uuid[]; v_r uuid[]; v_have int; v_left int;
  c_women int;   -- at least 30% of the drawn spots for women (Sam, Nov 17 2026: "70/30 is nice!")
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

  c_women := ceil(p_spots * 0.3);   -- 12 spots: at least 4
  -- 1. First-timers.
  select coalesce(array_agg(id), '{}') into v_ft from (
    select id from public.mic_signups where mic_date = p_date and status = 'hat' and first_time
     order by random() limit p_spots) x;
  v_left := p_spots - cardinality(v_ft);
  -- 2. Make sure at least 30% are women (by the first-name guess).
  select count(*) into v_have from public.mic_signups where id = any(v_ft) and women_spot;
  select coalesce(array_agg(id), '{}') into v_w from (
    select id from public.mic_signups where mic_date = p_date and status = 'hat' and women_spot and not (id = any(v_ft))
     order by random() limit least(v_left, greatest(c_women - v_have, 0))) x;
  v_left := v_left - cardinality(v_w);
  -- 3. Everyone else at random.
  select coalesce(array_agg(id), '{}') into v_r from (
    select id from public.mic_signups where mic_date = p_date and status = 'hat'
       and not (id = any(v_ft)) and not (id = any(v_w))
     order by random() limit v_left) x;

  with ordered as (select id, row_number() over (order by random()) as n from unnest(v_ft || v_w || v_r) as u(id))
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
