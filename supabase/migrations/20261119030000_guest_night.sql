-- "Your night": the guest's side of our own system (Sam, Nov 18 2026: "I want
-- to focus on the customer experience from check-out, through arrival, to
-- that first beer and knowing what is going on. Helping people get
-- comfortable in a new space quickly is key").
--
-- The page is night/index.html. It shows a guest what is happening right now
-- (doors in 40 minutes, doors are open, the show's on), how the night goes
-- step by step, and what's on tap. A guest who has tickets can pick their
-- first beer ahead of time; the bar sees it on firstround/index.html the
-- moment the door checks them in, and has it poured when they walk up.
--
-- Nothing here takes money. A picked beer is paid for at the bar when it is
-- handed over, the way every beer is today.
--
--   night_guests   one private link per line on the door list. The link's key
--                  is 32 random letters, so nobody can guess someone else's.
--                  No foreign key to tickets: the ticket sync deletes and
--                  re-adds door-list rows, and a guest's link and picks must
--                  survive that.
--   night_picks    the drinks a guest picked. Never deleted: a guest changing
--                  their mind marks it removed.
--
-- Guests have no login. The four guest functions are open to anyone, and the
-- key (or, for night_find, the email and last name on the order) is the only
-- way to a guest's own night. Without a key, night_look() gives only what is
-- already public: tonight's show and its start time.

create table if not exists public.night_guests (
  unique_id   text primary key,                 -- tickets.unique_id
  key         text not null unique default replace(gen_random_uuid()::text, '-', ''),
  show_date   text not null,
  show_title  text not null,
  made_at     timestamptz not null default now()
);

create table if not exists public.night_picks (
  id          bigint generated always as identity primary key,
  unique_id   text not null,                    -- tickets.unique_id
  item        text not null check (length(item) between 1 and 80),
  price       numeric(6, 2) check (price >= 0 and price <= 100),
  picked_at   timestamptz not null default now(),
  removed_at  timestamptz,                      -- the guest changed their mind
  poured_at   timestamptz,                      -- the bartender handed it over
  poured_by   uuid
);
create index if not exists night_picks_guest on public.night_picks (unique_id);

-- Only the functions below read or write these tables.
alter table public.night_guests enable row level security;
alter table public.night_picks  enable row level security;
revoke all on public.night_guests, public.night_picks from anon, authenticated;

create or replace function public.night_no_delete()
returns trigger language plpgsql as $$
begin
  raise exception 'Guest picks are never deleted.';
end $$;
create or replace trigger night_picks_keep before delete on public.night_picks
  for each row execute function public.night_no_delete();

-- When a door-list line's show starts. The calendar (exchange_showtimes, the
-- website's upcoming showtimes) knows; a website order is matched by its
-- showtime, anything else by the show's name and date. Empty when the show
-- isn't on the calendar (it is over, or was never on the website).
create or replace function public.night_starts_at(p_variant bigint, p_title text, p_date text)
returns timestamptz language sql stable security definer set search_path = public as $$
  select coalesce(
    (select s.starts_at from public.exchange_showtimes s where s.variant_id = p_variant),
    (select min(s.starts_at) from public.exchange_showtimes s where s.show_title = p_title and s.date_text = p_date))
$$;

-- What the page needs to know about one show. "late" is the second show of
-- a night: its doors open when the early show lets out, not half an hour
-- ahead, so the page words it differently.
create or replace function public.night_show(p_title text, p_date text, p_starts timestamptz)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'title', p_title, 'when', p_date, 'starts_at', p_starts,
    'free', coalesce((select bool_and(s.price = 0) from public.exchange_showtimes s
                      where s.show_title = p_title and s.starts_at = p_starts), false),
    'late', p_starts is not null and exists (
              select 1 from public.exchange_showtimes s
              where s.price > 0 and s.starts_at >= p_starts - interval '3 hours 30 minutes'
                and s.starts_at <= p_starts - interval '90 minutes'))
$$;

-- What the page shows.
--   With a guest's key: their show, their first name, how many tickets,
--   whether the door has checked them in, and the drinks they picked.
--   Without one (the tag by the door, a link someone shared): the show that
--   is on now or next, and anything else on the same night. Nothing private.
create or replace function public.night_look(p_key text default null)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare g public.night_guests; t public.tickets; v_start timestamptz; s record;
begin
  if p_key is not null and length(p_key) >= 20 then
    select * into g from public.night_guests where key = p_key;
    if g.unique_id is not null then
      select * into t from public.tickets where unique_id = g.unique_id;
    end if;
  end if;

  if t.unique_id is not null then
    v_start := public.night_starts_at(t.variant_id, t.show_title, t.show_date);
    return jsonb_build_object(
      'now', now(), 'found', true,
      'show', public.night_show(t.show_title, t.show_date, v_start),
      'guest', jsonb_build_object(
        'first', split_part(trim(coalesce(t.guest_name, '')), ' ', 1),
        'tickets', coalesce(t.tickets, 1),
        'reserved', coalesce(t.ticket_type, '') ~* '(vip|reserved)',
        'checked_in', coalesce(t.checked_in_count, 0) > 0,
        'checked_in_at', t.check_in_time),
      'picks', coalesce((select jsonb_agg(jsonb_build_object('id', p.id, 'item', p.item, 'price', p.price,
                   'poured', p.poured_at is not null) order by p.picked_at, p.id)
                 from public.night_picks p where p.unique_id = t.unique_id and p.removed_at is null), '[]'::jsonb));
  end if;

  -- Nobody we know. The show that's on now or next (a show stays "on" for
  -- three hours after it starts), and under "also" whatever else starts
  -- within eight hours of it: the same night, even when it runs past midnight.
  select x.show_title, x.date_text, x.starts_at into s
    from public.exchange_showtimes x
   where x.starts_at > now() - interval '3 hours'
   order by x.starts_at, x.show_title limit 1;
  if s.starts_at is null then
    return jsonb_build_object('now', now(), 'found', false, 'show', null, 'also', '[]'::jsonb);
  end if;
  return jsonb_build_object(
    'now', now(), 'found', false,
    'show', public.night_show(s.show_title, s.date_text, s.starts_at),
    'also', coalesce((select jsonb_agg(public.night_show(y.show_title, y.date_text, y.starts_at) order by y.starts_at)
               from (select distinct x.show_title, x.date_text, x.starts_at from public.exchange_showtimes x
                      where x.starts_at > now() - interval '3 hours'
                        and x.starts_at < s.starts_at + interval '8 hours'
                        and not (x.show_title = s.show_title and x.starts_at = s.starts_at)) y), '[]'::jsonb));
end $$;

-- "Find my tickets": a guest standing in line types the email they bought
-- with and their last name, and gets the key to their own night. Both have
-- to match one order for a show that hasn't happened yet; the soonest one
-- wins. The name has to be a whole word of the name on the order (or how it
-- ends, for a last name of several words), so two letters that happen to be
-- in everyone's name don't count. Returns nothing when there is no match,
-- without saying which part was wrong.
create or replace function public.night_find(p_email text, p_last text)
returns text language plpgsql security definer set search_path = public as $$
declare t public.tickets; v_key text;
        v_email text := lower(trim(coalesce(p_email, ''))); v_last text := lower(trim(coalesce(p_last, '')));
begin
  if v_email !~ '^[^@ ]+@[^@ ]+\.[^@ ]+$' or length(v_last) < 2 then return null; end if;
  select x.* into t from public.tickets x
   where lower(trim(x.email)) = v_email
     and (v_last = any (regexp_split_to_array(lower(trim(coalesce(x.guest_name, ''))), '[\s-]+'))
          or right(' ' || lower(trim(coalesce(x.guest_name, ''))), length(v_last) + 1) = ' ' || v_last)
     and public.night_starts_at(x.variant_id, x.show_title, x.show_date) > now() - interval '3 hours'
   order by public.night_starts_at(x.variant_id, x.show_title, x.show_date), x.unique_id
   limit 1;
  if t.unique_id is null then return null; end if;
  insert into public.night_guests (unique_id, show_date, show_title)
  values (t.unique_id, t.show_date, t.show_title)
  on conflict (unique_id) do update set show_date = excluded.show_date, show_title = excluded.show_title
  returning key into v_key;
  return v_key;
end $$;

-- The guest's door-list line for a key, or an error that reads well on the page.
create or replace function public.night_ticket(p_key text)
returns public.tickets language plpgsql stable security definer set search_path = public as $$
declare t public.tickets;
begin
  select x.* into t from public.tickets x join public.night_guests g on g.unique_id = x.unique_id
   where g.key = p_key and length(p_key) >= 20;
  if t.unique_id is null then
    raise exception 'We can''t find your tickets. Open the link from your email again, or ask at the door.';
  end if;
  return t;
end $$;

-- Pick a first beer. One for each ticket on the order, and only until the
-- show is over. It costs nothing to pick: it is paid for at the bar.
create or replace function public.night_pick(p_key text, p_item text, p_price numeric default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare t public.tickets; v_start timestamptz; v_item text := left(trim(coalesce(p_item, '')), 80); v_n int;
begin
  t := public.night_ticket(p_key);
  if v_item = '' then raise exception 'Pick something from the list.'; end if;
  v_start := public.night_starts_at(t.variant_id, t.show_title, t.show_date);
  if v_start is null and not public.door_is_tonight(t.show_date) then raise exception 'That show isn''t coming up.'; end if;
  if v_start < now() - interval '3 hours' then raise exception 'That show is over.'; end if;
  -- Two taps at once must not slip past the count.
  perform 1 from public.night_guests where unique_id = t.unique_id for update;
  select count(*) into v_n from public.night_picks where unique_id = t.unique_id and removed_at is null;
  if v_n >= coalesce(t.tickets, 1) then
    raise exception 'That''s one each. Order the next round at the bar or from your table.';
  end if;
  insert into public.night_picks (unique_id, item, price)
  values (t.unique_id, v_item, case when p_price >= 0 and p_price <= 100 then round(p_price, 2) end);
  return public.night_look(p_key);
end $$;

-- Change your mind, any time before it's handed over.
create or replace function public.night_unpick(p_key text, p_pick bigint)
returns jsonb language plpgsql security definer set search_path = public as $$
declare t public.tickets;
begin
  t := public.night_ticket(p_key);
  update public.night_picks set removed_at = now()
   where id = p_pick and unique_id = t.unique_id and removed_at is null and poured_at is null;
  return public.night_look(p_key);
end $$;

-- The bar's list for tonight: every drink picked for a show tonight, with
-- whether its guest is in the building yet. Staff logins only.
create or replace function public.night_bar()
returns jsonb language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_staff() then raise exception 'Sign in with a staff login to see the first round.'; end if;
  return jsonb_build_object('now', now(), 'picks', coalesce((
    select jsonb_agg(jsonb_build_object(
             'id', p.id, 'item', p.item, 'guest', t.guest_name, 'line', t.unique_id, 'tickets', coalesce(t.tickets, 1),
             'show', t.show_title, 'when', t.show_date,
             'here', coalesce(t.checked_in_count, 0) > 0, 'here_at', t.check_in_time,
             'poured_at', p.poured_at) order by t.check_in_time nulls last, t.guest_name, p.id)
      from public.night_picks p join public.tickets t on t.unique_id = p.unique_id
     where p.removed_at is null and public.door_is_tonight(t.show_date)), '[]'::jsonb));
end $$;

-- The bartender handed it over (or tapped it by mistake: p_undo).
create or replace function public.night_poured(p_pick bigint, p_undo boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  if not public.is_staff() then raise exception 'Sign in with a staff login to see the first round.'; end if;
  update public.night_picks
     set poured_at = case when p_undo then null else coalesce(poured_at, now()) end,
         poured_by = case when p_undo then null else coalesce(poured_by, auth.uid()) end
   where id = p_pick and removed_at is null;
  return public.night_bar();
end $$;

revoke all on function public.night_starts_at(bigint, text, text), public.night_show(text, text, timestamptz),
  public.night_ticket(text), public.night_look(text), public.night_find(text, text),
  public.night_pick(text, text, numeric), public.night_unpick(text, bigint),
  public.night_bar(), public.night_poured(bigint, boolean) from public, anon, authenticated;
grant execute on function public.night_look(text), public.night_find(text, text),
  public.night_pick(text, text, numeric), public.night_unpick(text, bigint) to anon, authenticated;
grant execute on function public.night_bar(), public.night_poured(bigint, boolean) to authenticated;
