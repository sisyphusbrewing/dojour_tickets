-- Any staff login may put money on a gift card, not only managers (Sam,
-- Nov 17 2026, picked "Yes, any staff": cards sell at night at the bar, on a
-- phone kept there, "so folks could add/subtract to it easily"). Still at
-- most $500 a load, every load logged with who did it, and the week's total
-- sold sits on the Gift cards page to check against GoTab. The door login
-- (shared, used by comics) still can't.

-- Put money on (a card sold or topped up). Any staff login (Sam, Nov 17 2026).
create or replace function public.gift_card_load(p_code text, p_amount numeric, p_note text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare c public.gift_cards;
begin
  if not public.is_staff() then raise exception 'Sign in with your own staff login to put money on a card.'; end if;
  c := public.gift_card_by_code(p_code);
  if not c.active then raise exception 'This card was switched off.'; end if;
  if p_amount is null or p_amount <= 0 then raise exception 'Type how much to put on.'; end if;
  if p_amount <> round(p_amount, 2) then raise exception 'Use dollars and cents.'; end if;
  if p_amount > public.gift_max_load() then raise exception 'At most $% at a time.', public.gift_max_load(); end if;
  return public.gift_write(c.id, 'load', p_amount, p_note);
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
      'can_load', true,
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
