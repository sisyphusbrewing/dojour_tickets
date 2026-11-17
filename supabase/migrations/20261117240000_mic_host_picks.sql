-- Tuesday open mic: the host, the host's guaranteed spots, and the 6:30 draw.
--
-- Sam, Nov 17 2026: "We will put the host name in ahead of time and send them
-- a link to submit 4 names for people that will each get 5-7 minutes as
-- guaranteed spots." / "Then at 6:30pm We should select 12 random people to
-- finish the lineup." / "So it would be the Host, then some randoms, then a
-- prebooked person, then some randoms, etc until we get through all the people."
--
-- How it works:
-- * Staff type the host's name for a Tuesday on mic/host.html. That makes a
--   private link (mic/picks.html?k=...) for the host, who needs no login.
-- * On that link the host types up to 4 comics (rows marked host_pick, status
--   'booked'). They can change them until the end of that Tuesday. Replaced
--   picks are marked cancelled, never deleted.
-- * At 6:30 PM (when online sign-ups close) mic_draw() picks 12 names at random
--   from the hat, once. The staff page and the host's page both ask for it as
--   soon as it's 6:30, so it happens whichever is open first.
-- * Running order (mic_renumber): the host opens the show (not a numbered
--   spot), then a block of drawn names, then a guaranteed comic, then another
--   block, and so on. The drawn names are split evenly so each guaranteed comic
--   closes a block: 12 drawn and 4 picks = 3, pick, 3, pick, 3, pick, 3, pick.
--   Host picks come before comics staff booked ahead by hand.
-- * At 6:35 PM the running order goes up on the public sign-up page (the open
--   mic page on the website), stage names only (Sam, Nov 17 2026: "at 6:35
--   the list should automatically post online"). mic_public_lineup().

create table if not exists public.mic_hosts (
  mic_date    date primary key,                    -- the Tuesday
  host_name   text not null,
  token       text not null unique default replace(gen_random_uuid()::text, '-', ''),
  picks_at    timestamptz,                         -- when the host last sent names
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create trigger mic_hosts_set_updated_at
  before update on public.mic_hosts
  for each row execute function public.set_updated_at();

alter table public.mic_hosts enable row level security;
-- Staff signed in can read and set hosts. The public can't read the table
-- (the links live in it); the host's page only goes through functions that
-- need the link's code.
create policy "Allow authenticated staff full access to mic_hosts"
  on public.mic_hosts for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to mic_hosts"
  on public.mic_hosts for all to service_role using (true) with check (true);
revoke all on public.mic_hosts from anon;

-- One row per Tuesday once the draw has run, so the 6:30 draw happens once.
-- "Undo the draw" on the staff page puts names back in the hat but keeps this
-- row, so the automatic draw doesn't redo it behind the host's back; the
-- Draw button still works by hand.
create table if not exists public.mic_draws (
  mic_date  date primary key,
  spots     int not null,
  how       text not null check (how in ('auto', 'by hand')),
  drawn_at  timestamptz not null default now()
);
alter table public.mic_draws enable row level security;
create policy "Allow authenticated staff to read mic_draws"
  on public.mic_draws for select to authenticated using (true);
create policy "Allow service_role full access to mic_draws"
  on public.mic_draws for all to service_role using (true) with check (true);
revoke all on public.mic_draws from anon, authenticated;
grant select on public.mic_draws to authenticated;

alter table public.mic_signups add column if not exists host_pick boolean not null default false;

-- Put a Tuesday's lineup in running order (see the top of this file).
create or replace function public.mic_renumber(p_date date)
returns void language plpgsql security definer set search_path = public as $$
declare
  v_pre uuid[]; v_rand uuid[]; v_line uuid[] := '{}';
  p int; r int; i int; j int; k int := 0; take int;
begin
  select coalesce(array_agg(id order by host_pick desc, slot nulls last, created_at), '{}') into v_pre
    from public.mic_signups where mic_date = p_date and status = 'booked';
  select coalesce(array_agg(id order by slot nulls last, created_at), '{}') into v_rand
    from public.mic_signups where mic_date = p_date and status = 'drawn';
  p := cardinality(v_pre); r := cardinality(v_rand);
  if p = 0 then
    v_line := v_rand;
  else
    for i in 1..p loop
      take := (r * i) / p - (r * (i - 1)) / p;
      for j in 1..take loop k := k + 1; v_line := v_line || v_rand[k]; end loop;
      v_line := v_line || v_pre[i];
    end loop;
  end if;
  update public.mic_signups s set slot = x.n
    from unnest(v_line) with ordinality as x(id, n)
   where s.id = x.id and s.slot is distinct from x.n::int;
  update public.mic_signups set slot = null
   where mic_date = p_date and status not in ('booked', 'drawn') and slot is not null;
end $$;

-- The draw. p_by_hand = the staff Draw button (any time, staff only).
-- Otherwise it's the automatic 6:30 draw: anyone's page may ask, but it only
-- happens from 6:30 PM Central on that Tuesday and only once.
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
  with pick as (
    select id, row_number() over (order by random()) as n
      from public.mic_signups where mic_date = p_date and status = 'hat')
  update public.mic_signups s
     set status = case when p.n <= p_spots then 'drawn' else 'not_drawn' end,
         slot   = case when p.n <= p_spots then 1000 + p.n::int else null end
    from pick p where s.id = p.id;
  get diagnostics v_n = row_count;
  insert into public.mic_draws (mic_date, spots, how)
    values (p_date, p_spots, case when p_by_hand then 'by hand' else 'auto' end)
    on conflict (mic_date) do update set spots = excluded.spots, how = excluded.how, drawn_at = now();
  perform public.mic_renumber(p_date);
  select count(*) into v_n from public.mic_signups where mic_date = p_date and status = 'drawn';
  return jsonb_build_object('drawn', v_n);
end $$;

-- What the host's page shows: the Tuesday, the host, their picks, and once
-- names are drawn, the whole running order.
create or replace function public.mic_host_get(p_token text)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'mic_date', h.mic_date,
    'host_name', h.host_name,
    'open', h.mic_date >= (now() at time zone 'America/Chicago')::date,
    'drawn', exists (select 1 from public.mic_signups s where s.mic_date = h.mic_date and s.status in ('drawn', 'not_drawn')),
    'lineup', coalesce((select jsonb_agg(jsonb_build_object('name', s.name, 'how',
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

-- The host sends (or changes) the guaranteed names. Up to 4, in their order.
create or replace function public.mic_host_save(p_token text, p_names text[])
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  h public.mic_hosts;
  v_names text[] := '{}';
  v_name text;
  v_first int;
  i int := 0;
begin
  select * into h from public.mic_hosts where token = p_token and length(coalesce(p_token, '')) >= 20;
  if not found then
    raise exception 'This link doesn''t work any more. Ask Sisyphus for a new one.';
  end if;
  if h.mic_date < (now() at time zone 'America/Chicago')::date then
    raise exception 'That mic is over.';
  end if;
  foreach v_name in array coalesce(p_names, '{}') loop
    v_name := left(trim(coalesce(v_name, '')), 80);
    if v_name <> '' then v_names := v_names || v_name; end if;
  end loop;
  if cardinality(v_names) > 4 then
    raise exception 'Four guaranteed spots at most.';
  end if;

  -- The old picks come off (kept, marked cancelled), the new ones go on.
  update public.mic_signups set status = 'cancelled', slot = null
   where mic_date = h.mic_date and host_pick and status <> 'cancelled';
  select coalesce(min(slot), 1) into v_first from public.mic_signups where mic_date = h.mic_date and status = 'booked';
  foreach v_name in array v_names loop
    i := i + 1;
    insert into public.mic_signups (mic_date, name, status, slot, host_pick, staff_notes)
      values (h.mic_date, v_name, 'booked', v_first - 10 + i, true, 'Host pick (' || h.host_name || ')');
  end loop;
  perform public.mic_renumber(h.mic_date);

  update public.mic_hosts set picks_at = now() where mic_date = h.mic_date;
  return jsonb_build_object('mic_date', h.mic_date, 'saved', cardinality(v_names));
end $$;

-- Tonight's running order for the public page: only on a Tuesday's own date,
-- only from 6:35 PM Central, only once names are drawn. Names only.
create or replace function public.mic_public_lineup()
returns jsonb language sql stable security definer set search_path = public as $$
  with n as (select (now() at time zone 'America/Chicago') as t)
  select case
    when (select t::time from n) < time '18:35' then null
    when not exists (select 1 from public.mic_signups s where s.mic_date = (select t::date from n) and s.status in ('drawn', 'not_drawn')) then null
    else jsonb_build_object(
      'mic_date', (select t::date from n),
      'host_name', (select h.host_name from public.mic_hosts h where h.mic_date = (select t::date from n)),
      'lineup', coalesce((select jsonb_agg(s.name order by s.slot nulls last, s.created_at)
                            from public.mic_signups s
                           where s.mic_date = (select t::date from n) and s.status in ('booked', 'drawn')), '[]'::jsonb))
  end
$$;
revoke all on function public.mic_public_lineup() from public;
grant execute on function public.mic_public_lineup() to anon, authenticated, service_role;

revoke all on function public.mic_renumber(date) from public;
revoke all on function public.mic_draw(date, int, boolean) from public;
revoke all on function public.mic_host_get(text) from public;
revoke all on function public.mic_host_save(text, text[]) from public;
grant execute on function public.mic_renumber(date) to authenticated, service_role;
grant execute on function public.mic_draw(date, int, boolean) to anon, authenticated, service_role;
grant execute on function public.mic_host_get(text) to anon, authenticated, service_role;
grant execute on function public.mic_host_save(text, text[]) to anon, authenticated, service_role;
