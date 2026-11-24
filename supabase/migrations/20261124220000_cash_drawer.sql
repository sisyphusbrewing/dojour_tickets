-- Counting the cash drawer on the Clock page (Sam, Nov 24 2026: "the employees
-- could count the cash and put that into the portal when the first person of
-- the day clocks in" ... "Then they can count at the end of the night ... and
-- we can compare later").
--
-- Until Nov 24 2026 the bar took no cash. GoTab can keep a cash account per
-- day, but its "close out every day" rule greyed the Cash buttons whenever a
-- day was left open (Sam: "the Cash Drawer buttons get greyed out"). So GoTab
-- now keeps one cash account per register that never closes, and the counting
-- happens here instead:
--   - The first person to clock in on a day is asked to count the drawer
--     (it should start at $300). That is the "open" count.
--   - The last person to clock out is asked to count it again. That is the
--     "close" count.
--   - Close minus open is the cash that came in. Each morning Claude reads
--     how much cash GoTab took that day and writes it into cash_gotab, and the
--     Payroll tab shows the three side by side, so a short drawer stands out.
-- Counts are bills by how many of each, plus the coins as one dollar amount.
-- Nothing is ever changed or deleted: a recount is a new row, and the newest
-- count of each kind is the one that counts.

-- ---------- Settings: what the drawer starts the day with ----------
create table if not exists public.cash_settings (
  id boolean primary key default true check (id),      -- one row only
  start_amount numeric(8,2) not null default 300        -- Sam, Nov 24 2026: $300
);
insert into public.cash_settings (id) values (true) on conflict (id) do nothing;
alter table public.cash_settings enable row level security;   -- no policies: functions only

-- ---------- The counts ----------
create table if not exists public.cash_counts (
  id bigint generated always as identity primary key,
  cash_day date not null,                       -- the bar's day (a 1 AM close belongs to the day before)
  kind text not null check (kind in ('open', 'close')),
  counted_by uuid not null references auth.users (id) on delete restrict,
  counted_at timestamptz not null default now(),
  bills jsonb not null default '{}'::jsonb,     -- {"100":0,"50":1,"20":10,"10":5,"5":8,"1":30}
  coins numeric(8,2) not null default 0 check (coins >= 0 and coins < 1000),
  total numeric(10,2) not null check (total >= 0 and total < 100000),
  note text not null default ''
);
create index if not exists cash_counts_day_idx on public.cash_counts (cash_day, kind, counted_at desc);
alter table public.cash_counts enable row level security;
drop policy if exists "Managers see counts" on public.cash_counts;
create policy "Managers see counts" on public.cash_counts for select to authenticated
  using ((select public.is_manager()));

-- ---------- What GoTab says came in as cash, per day ----------
-- Written each morning by Claude (with the service key), from GoTab Manager.
create table if not exists public.cash_gotab (
  cash_day date primary key,
  gotab_cash numeric(10,2) not null,
  read_at timestamptz not null default now(),
  note text not null default ''
);
alter table public.cash_gotab enable row level security;
drop policy if exists "Managers see GoTab cash" on public.cash_gotab;
create policy "Managers see GoTab cash" on public.cash_gotab for select to authenticated
  using ((select public.is_manager()));

-- Supabase hands new tables to the website's logins with full rights. These
-- hold money records, so: read only (the rules above say who), and nothing is
-- written except through the functions below.
revoke all on public.cash_settings, public.cash_counts, public.cash_gotab from anon, authenticated;
grant select on public.cash_counts, public.cash_gotab to authenticated;

-- Nothing in cash_counts is ever changed or deleted, not even with the service key.
create or replace function public.cash_counts_frozen()
returns trigger language plpgsql as $$
begin
  raise exception 'Drawer counts are never changed or deleted. Count again instead.';
end $$;
drop trigger if exists cash_counts_frozen on public.cash_counts;
create trigger cash_counts_frozen before update or delete on public.cash_counts
  for each row execute function public.cash_counts_frozen();

-- The bar's day. Before 5 AM it is still last night, so a count at 1:30 AM
-- closes the day that opened that afternoon.
create or replace function public.cash_day()
returns date language sql stable set search_path = public as $$
  select ((now() at time zone 'America/Chicago') - interval '5 hours')::date
$$;

-- One count as the page shows it.
create or replace function public.cash_count_json(c public.cash_counts)
returns jsonb language sql stable security definer set search_path = public as $$
  select case when c.id is null then null else
    jsonb_build_object('id', c.id, 'total', c.total, 'at', c.counted_at,
                       'by', public.schedule_name(c.counted_by), 'note', c.note) end
$$;

-- Where the drawer stands today, for the Clock page.
--   open_due:  nobody has counted it yet today.
--   close_due: nobody has counted it at the end of today yet, and nobody else
--              is on the clock (so whoever clocks out now is the last one).
create or replace function public.cash_status()
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare v_me uuid := auth.uid();
        v_day date := public.cash_day();
        v_open public.cash_counts;
        v_close public.cash_counts;
        v_others int;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  select * into v_open from public.cash_counts where cash_day = v_day and kind = 'open' order by counted_at desc limit 1;
  select * into v_close from public.cash_counts where cash_day = v_day and kind = 'close' order by counted_at desc limit 1;
  select count(distinct user_id) into v_others from public.time_punches
   where user_id <> v_me and clock_out is null and not removed and clock_in > now() - public.clock_forgot_after();
  return jsonb_build_object(
    'day', v_day,
    'start', (select start_amount from public.cash_settings),
    'open', public.cash_count_json(v_open),
    'close', public.cash_count_json(v_close),
    'others_on', v_others,
    'open_due', v_open.id is null,
    'close_due', v_close.id is null and v_others = 0);
end $$;

-- Save a count. p_bills is how many of each bill: {"100":0,"20":10,...};
-- p_coins is the coins as one dollar amount. The total is worked out here.
create or replace function public.cash_count_save(p_kind text, p_bills jsonb, p_coins numeric default 0, p_note text default '')
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_total numeric := 0;
        k text; v text; n int;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  if p_kind not in ('open', 'close') then raise exception 'A count is either the opening count or the closing count.'; end if;
  if p_bills is null or jsonb_typeof(p_bills) <> 'object' then raise exception 'Say how many of each bill.'; end if;
  for k, v in select key, value #>> '{}' from jsonb_each(p_bills) loop
    if k not in ('100', '50', '20', '10', '5', '2', '1') then raise exception 'There is no $% bill.', k; end if;
    if v !~ '^\d{1,4}$' then raise exception 'Count the $% bills as a whole number.', k; end if;
    n := v::int;
    v_total := v_total + n * k::int;
  end loop;
  if p_coins is null or p_coins < 0 or p_coins >= 1000 or p_coins <> round(p_coins, 2) then
    raise exception 'Type the coins as a dollar amount, like 4.35.'; end if;
  v_total := v_total + p_coins;
  insert into public.cash_counts (cash_day, kind, counted_by, bills, coins, total, note)
  values (public.cash_day(), p_kind, auth.uid(), p_bills, p_coins, v_total, left(coalesce(trim(p_note), ''), 300));
  return public.cash_status();
end $$;

-- For managers on the Payroll tab: each day's counts next to what GoTab took.
--   came_in    = closing count minus opening count
--   difference = came_in minus GoTab's cash (negative = the drawer is short)
create or replace function public.cash_days(p_from date, p_thru date)
returns table (cash_day date, open_total numeric, open_by text, close_total numeric, close_by text,
               came_in numeric, gotab_cash numeric, difference numeric, counts int)
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  return query
  with days as (
    select c.cash_day from public.cash_counts c where c.cash_day between p_from and p_thru
    union select g.cash_day from public.cash_gotab g where g.cash_day between p_from and p_thru
  ), o as (
    select distinct on (c.cash_day) c.cash_day, c.total, c.counted_by from public.cash_counts c
     where c.kind = 'open' and c.cash_day between p_from and p_thru order by c.cash_day, c.counted_at desc
  ), cl as (
    select distinct on (c.cash_day) c.cash_day, c.total, c.counted_by from public.cash_counts c
     where c.kind = 'close' and c.cash_day between p_from and p_thru order by c.cash_day, c.counted_at desc
  )
  select d.cash_day, o.total, public.schedule_name(o.counted_by), cl.total, public.schedule_name(cl.counted_by),
         cl.total - o.total, g.gotab_cash, cl.total - o.total - g.gotab_cash,
         (select count(*)::int from public.cash_counts c where c.cash_day = d.cash_day)
    from days d
    left join o on o.cash_day = d.cash_day
    left join cl on cl.cash_day = d.cash_day
    left join public.cash_gotab g on g.cash_day = d.cash_day
   order by d.cash_day desc;
end $$;

revoke all on function public.cash_day(), public.cash_count_json(public.cash_counts), public.cash_status(),
  public.cash_count_save(text, jsonb, numeric, text), public.cash_days(date, date), public.cash_counts_frozen() from public, anon;
grant execute on function public.cash_day(), public.cash_status(),
  public.cash_count_save(text, jsonb, numeric, text), public.cash_days(date, date) to authenticated;
