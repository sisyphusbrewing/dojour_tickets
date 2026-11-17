-- Gift cards you tap (Sam, Nov 17 2026: "I want to offer gift cards now with
-- the NFC chip writing ability"). Spent at the club only, not on the website
-- (Sam, Nov 17 2026, picked "At the club only").
--
-- Each card is a blank NFC card with one link written on it:
--   https://staff.sisyphusbrewing.com/gift/?c=<code>
-- The code is 32 random letters and numbers, so nobody can guess another
-- card's link. Anyone who taps the card sees its balance and nothing else.
-- Only a signed-in staff login can take money off, and only a manager or
-- the owner can put money on.
--
-- Money is never stored as "the balance". Every change is its own row in
-- gift_card_moves (who, when, how much, the balance after), and the balance
-- is the sum of those rows. Nothing here is ever deleted or changed: an undo
-- is a new row going the other way, and a lost card is switched off with its
-- money moved to a new card in two more rows.
--
-- Minnesota law: gift cards can't expire and can't carry fees. These don't.
--
-- GoTab can't read these cards (no API). Staff ring the sale and the payment
-- in GoTab as usual and do the balance here; see gift/index.html.

create table if not exists public.gift_cards (
  id          bigint generated always as identity primary key,
  number      int not null unique,              -- printed on the card, for when a phone can't tap
  code        text not null unique check (code ~ '^[a-f0-9]{32}$'),
  active      boolean not null default true,    -- false = switched off (lost, replaced)
  off_reason  text,
  moved_to    bigint references public.gift_cards (id),
  made_at     timestamptz not null default now(),
  made_by     uuid
);

create table if not exists public.gift_card_moves (
  id            bigint generated always as identity primary key,
  card_id       bigint not null references public.gift_cards (id),
  at            timestamptz not null default now(),
  by_user       uuid,
  by_name       text,
  kind          text not null check (kind in ('load', 'spend', 'undo', 'move_in', 'move_out')),
  amount        numeric(10, 2) not null check (amount <> 0),   -- + puts money on, - takes it off
  balance_after numeric(10, 2) not null check (balance_after >= 0),
  note          text,
  undoes        bigint unique references public.gift_card_moves (id)   -- a move can be undone once
);
create index if not exists gift_card_moves_card on public.gift_card_moves (card_id, at);

-- Only the functions below read or write these tables.
alter table public.gift_cards enable row level security;
alter table public.gift_card_moves enable row level security;
revoke all on public.gift_cards, public.gift_card_moves from anon, authenticated;

-- Rows are never changed or removed, by anyone, the service key included.
create or replace function public.gift_no_rewrite()
returns trigger language plpgsql as $$
begin
  if tg_table_name = 'gift_cards' and tg_op = 'UPDATE' then
    if new.id = old.id and new.number = old.number and new.code = old.code
       and new.made_at = old.made_at and old.active and not new.active then
      return new;                                  -- switching a card off is the one change allowed
    end if;
  end if;
  raise exception 'Gift card records are never changed or deleted.';
end $$;
drop trigger if exists gift_cards_keep on public.gift_cards;
create trigger gift_cards_keep before update or delete on public.gift_cards
  for each row execute function public.gift_no_rewrite();
drop trigger if exists gift_card_moves_keep on public.gift_card_moves;
create trigger gift_card_moves_keep before update or delete on public.gift_card_moves
  for each row execute function public.gift_no_rewrite();

-- The most a single Load can put on, and the most a card can hold. A typo
-- of $2500 for $25 gets stopped here.
create or replace function public.gift_max_load() returns numeric language sql immutable as $$ select 500::numeric $$;
create or replace function public.gift_max_balance() returns numeric language sql immutable as $$ select 1000::numeric $$;
-- How long the person who made a change can undo it themselves.
create or replace function public.gift_undo_window() returns interval language sql immutable as $$ select interval '2 minutes' $$;

create or replace function public.gift_balance_of(p_card bigint)
returns numeric language sql stable security definer set search_path = public as $$
  select coalesce(sum(amount), 0)::numeric(10, 2) from public.gift_card_moves where card_id = p_card
$$;

create or replace function public.gift_my_name()
returns text language sql stable security definer set search_path = public, auth as $$
  select coalesce(nullif(trim(r.display_name), ''), split_part(u.email, '@', 1))
  from auth.users u left join public.staff_roles r on r.user_id = u.id
  where u.id = auth.uid()
$$;

-- Writes one move and returns the new balance. Locks the card first, so two
-- phones taking money off the same card at once can't both spend the last $10.
create or replace function public.gift_write(p_card bigint, p_kind text, p_amount numeric, p_note text, p_undoes bigint default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_bal numeric; v_after numeric; v_id bigint;
begin
  perform 1 from public.gift_cards where id = p_card for update;
  v_bal := public.gift_balance_of(p_card);
  v_after := v_bal + p_amount;
  if v_after < 0 then
    raise exception 'Only $% left on this card.', to_char(v_bal, 'FM999990.00');
  end if;
  if p_amount > 0 and v_after > public.gift_max_balance() then
    raise exception 'A card can hold at most $%.', public.gift_max_balance();
  end if;
  insert into public.gift_card_moves (card_id, by_user, by_name, kind, amount, balance_after, note, undoes)
  values (p_card, auth.uid(), public.gift_my_name(), p_kind, p_amount, v_after, nullif(trim(coalesce(p_note, '')), ''), p_undoes)
  returning id into v_id;
  return jsonb_build_object('move', v_id, 'balance', v_after);
end $$;

-- The card a link points to, or an error that reads well on the page.
create or replace function public.gift_card_by_code(p_code text)
returns public.gift_cards language plpgsql stable security definer set search_path = public as $$
declare c public.gift_cards;
begin
  select * into c from public.gift_cards where code = lower(trim(coalesce(p_code, '')));
  if c.id is null then raise exception 'This isn''t one of our gift cards.'; end if;
  return c;
end $$;

-- What a tap shows. Anyone (a guest, no login): the card's number and
-- balance. Staff also get the history and what they may do.
create or replace function public.gift_card_look(p_code text)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare c public.gift_cards; v jsonb; v_staff boolean := public.is_staff();
begin
  select * into c from public.gift_cards where code = lower(trim(coalesce(p_code, '')));
  if c.id is null then return jsonb_build_object('found', false); end if;
  v := jsonb_build_object('found', true, 'number', c.number, 'active', c.active,
         'balance', public.gift_balance_of(c.id),
         'loaded', exists (select 1 from public.gift_card_moves where card_id = c.id),
         'staff', v_staff);
  if v_staff then
    v := v || jsonb_build_object(
      'can_load', public.is_manager(),
      'off_reason', c.off_reason,
      'moved_to', (select number from public.gift_cards where id = c.moved_to),
      'moves', coalesce((select jsonb_agg(jsonb_build_object('id', m.id, 'at', m.at, 'kind', m.kind,
                 'amount', m.amount, 'balance_after', m.balance_after, 'by', m.by_name, 'note', m.note,
                 'undone', exists (select 1 from public.gift_card_moves u where u.undoes = m.id),
                 'can_undo', m.kind in ('load', 'spend') and m.by_user = auth.uid()
                             and m.at > now() - public.gift_undo_window()
                             and not exists (select 1 from public.gift_card_moves u where u.undoes = m.id))
                 order by m.at desc, m.id desc)
               from (select * from public.gift_card_moves where card_id = c.id order by at desc, id desc limit 30) m), '[]'::jsonb));
  end if;
  return v;
end $$;

-- Take money off (paying for something). Any staff login.
create or replace function public.gift_card_spend(p_code text, p_amount numeric, p_note text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare c public.gift_cards;
begin
  if not public.is_staff() then raise exception 'Sign in with your own staff login to take money off a card.'; end if;
  c := public.gift_card_by_code(p_code);
  if not c.active then raise exception 'This card was switched off.'; end if;
  if p_amount is null or p_amount <= 0 then raise exception 'Type how much to take off.'; end if;
  if p_amount <> round(p_amount, 2) then raise exception 'Use dollars and cents.'; end if;
  return public.gift_write(c.id, 'spend', -p_amount, p_note);
end $$;

-- Put money on (a card sold or topped up). Managers and the owner.
create or replace function public.gift_card_load(p_code text, p_amount numeric, p_note text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare c public.gift_cards;
begin
  if not public.is_manager() then raise exception 'Only a manager can put money on a card.'; end if;
  c := public.gift_card_by_code(p_code);
  if not c.active then raise exception 'This card was switched off.'; end if;
  if p_amount is null or p_amount <= 0 then raise exception 'Type how much to put on.'; end if;
  if p_amount <> round(p_amount, 2) then raise exception 'Use dollars and cents.'; end if;
  if p_amount > public.gift_max_load() then raise exception 'At most $% at a time.', public.gift_max_load(); end if;
  return public.gift_write(c.id, 'load', p_amount, p_note);
end $$;

-- Undo your own Load or Take off within two minutes. It adds a row going the
-- other way; the first row stays.
create or replace function public.gift_card_undo(p_move bigint)
returns jsonb language plpgsql security definer set search_path = public as $$
declare m public.gift_card_moves;
begin
  if not public.is_staff() then raise exception 'Sign in first.'; end if;
  select * into m from public.gift_card_moves where id = p_move;
  if m.id is null or m.kind not in ('load', 'spend') or m.by_user is distinct from auth.uid() then
    raise exception 'You can only undo your own change.';
  end if;
  if m.at < now() - public.gift_undo_window() then raise exception 'Too late to undo. Ask a manager.'; end if;
  if exists (select 1 from public.gift_card_moves where undoes = m.id) then raise exception 'Already undone.'; end if;
  return public.gift_write(m.card_id, 'undo', -m.amount, null, m.id);
end $$;

-- Find a card by the number printed on it, for a phone that won't tap.
-- Staff only: it hands back the card's code.
create or replace function public.gift_card_find(p_number int)
returns text language plpgsql stable security definer set search_path = public as $$
declare v text;
begin
  if not public.is_staff() then raise exception 'Sign in first.'; end if;
  select code into v from public.gift_cards where number = p_number;
  if v is null then raise exception 'No card #%.', p_number; end if;
  return v;
end $$;

-- Make new blank cards (managers). Each gets the next number and a fresh code.
create or replace function public.gift_cards_make(p_count int)
returns int language plpgsql security definer set search_path = public as $$
declare i int; v_next int;
begin
  if not public.is_manager() then raise exception 'Only a manager can make new cards.'; end if;
  if p_count is null or p_count < 1 or p_count > 50 then raise exception 'Make 1 to 50 at a time.'; end if;
  lock table public.gift_cards in exclusive mode;
  select coalesce(max(number), 0) + 1 into v_next from public.gift_cards;
  for i in 0 .. p_count - 1 loop
    insert into public.gift_cards (number, code, made_by)
    values (v_next + i, replace(gen_random_uuid()::text, '-', '') , auth.uid());
  end loop;
  return p_count;
end $$;

-- Switch off a lost or broken card and move what's on it to another card
-- (managers). The old card's link then says it was switched off.
create or replace function public.gift_card_switch_off(p_number int, p_to_number int, p_reason text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare a public.gift_cards; b public.gift_cards; v_bal numeric;
begin
  if not public.is_manager() then raise exception 'Only a manager can switch off a card.'; end if;
  select * into a from public.gift_cards where number = p_number for update;
  if a.id is null then raise exception 'No card #%.', p_number; end if;
  if not a.active then raise exception 'Card #% is already switched off.', p_number; end if;
  if p_to_number is not null then
    select * into b from public.gift_cards where number = p_to_number for update;
    if b.id is null then raise exception 'No card #%.', p_to_number; end if;
    if b.id = a.id or not b.active then raise exception 'Pick a different card that works.'; end if;
  end if;
  v_bal := public.gift_balance_of(a.id);
  if v_bal > 0 and b.id is null then raise exception 'Card #% still has $% on it. Pick the card to move it to.', p_number, to_char(v_bal, 'FM999990.00'); end if;
  if v_bal > 0 then
    perform public.gift_write(a.id, 'move_out', -v_bal, 'To card #' || b.number);
    perform public.gift_write(b.id, 'move_in', v_bal, 'From card #' || a.number);
  end if;
  update public.gift_cards set active = false, off_reason = nullif(trim(coalesce(p_reason, '')), ''), moved_to = b.id where id = a.id;
  return jsonb_build_object('moved', v_bal, 'to', b.number);
end $$;

-- Every card for the managers' list: number, link code (to write a new
-- card), balance, last use. Plus the totals.
create or replace function public.gift_cards_list()
returns jsonb language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  return jsonb_build_object(
    'cards', coalesce((select jsonb_agg(jsonb_build_object('number', c.number, 'code', c.code, 'active', c.active,
               'balance', public.gift_balance_of(c.id),
               'loaded', exists (select 1 from public.gift_card_moves where card_id = c.id),
               'last', (select max(at) from public.gift_card_moves where card_id = c.id))
               order by c.number desc) from public.gift_cards c), '[]'::jsonb),
    -- What's still out on cards: money we owe in drinks and tickets.
    'outstanding', (select coalesce(sum(amount), 0) from public.gift_card_moves));
end $$;

-- Every change between two days (Minneapolis), newest first, with totals:
-- what was sold (loads) and what was spent. To check against GoTab.
create or replace function public.gift_card_report(p_from date, p_to date)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare v_from timestamptz; v_to timestamptz;
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  v_from := (p_from::timestamp at time zone 'America/Chicago');
  v_to := ((p_to + 1)::timestamp at time zone 'America/Chicago');
  return jsonb_build_object(
    'sold',  (select coalesce(sum(case when m.kind = 'load' then m.amount
                                       when m.kind = 'undo' and o.kind = 'load' then m.amount end), 0)
              from public.gift_card_moves m left join public.gift_card_moves o on o.id = m.undoes
              where m.at >= v_from and m.at < v_to),
    'spent', (select coalesce(-sum(case when m.kind = 'spend' then m.amount
                                        when m.kind = 'undo' and o.kind = 'spend' then m.amount end), 0)
              from public.gift_card_moves m left join public.gift_card_moves o on o.id = m.undoes
              where m.at >= v_from and m.at < v_to),
    'moves', coalesce((select jsonb_agg(jsonb_build_object('at', m.at, 'number', c.number, 'kind', m.kind,
               'amount', m.amount, 'balance_after', m.balance_after, 'by', m.by_name, 'note', m.note)
               order by m.at desc, m.id desc)
               from public.gift_card_moves m join public.gift_cards c on c.id = m.card_id
               where m.at >= v_from and m.at < v_to), '[]'::jsonb));
end $$;

revoke all on function public.gift_no_rewrite(), public.gift_balance_of(bigint), public.gift_my_name(),
  public.gift_write(bigint, text, numeric, text, bigint), public.gift_card_by_code(text),
  public.gift_card_look(text), public.gift_card_spend(text, numeric, text), public.gift_card_load(text, numeric, text),
  public.gift_card_undo(bigint), public.gift_card_find(int), public.gift_cards_make(int),
  public.gift_card_switch_off(int, int, text), public.gift_cards_list(), public.gift_card_report(date, date)
  from public, anon, authenticated;
-- A guest's phone (no login) may only look.
grant execute on function public.gift_card_look(text) to anon, authenticated;
grant execute on function public.gift_card_spend(text, numeric, text), public.gift_card_load(text, numeric, text),
  public.gift_card_undo(bigint), public.gift_card_find(int), public.gift_cards_make(int),
  public.gift_card_switch_off(int, int, text), public.gift_cards_list(), public.gift_card_report(date, date)
  to authenticated;
