-- The Boulder, the gift card station at the front (Sam, Nov 18 2026: "people
-- can type the amount in and hit add and write the card right there"). Its
-- New card button needs a fresh card number and link, so any staff login may
-- now make ONE new card at a time (Sam, Nov 18 2026, picked "Yes, from the
-- station"). Managers can still make a batch on the Gift cards page.
--
-- The station then writes the link onto a blank card, reads it back, locks
-- the card, and only then puts the money on with gift_card_load(). If the
-- write fails, the new card just stays blank and unused: nothing to undo.
--
-- A stop against a stuck button or a script: at most 30 new cards per login
-- per day.

create or replace function public.gift_card_new()
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_next int; v_code text; v_today int;
begin
  if not public.is_staff() then raise exception 'Sign in with your own staff login to make a card.'; end if;
  select count(*) into v_today from public.gift_cards
   where made_by = auth.uid() and made_at > now() - interval '1 day';
  if v_today >= 30 then raise exception 'That''s 30 new cards today from this login. Ask a manager.'; end if;
  lock table public.gift_cards in exclusive mode;
  select coalesce(max(number), 0) + 1 into v_next from public.gift_cards;
  v_code := replace(gen_random_uuid()::text, '-', '');
  insert into public.gift_cards (number, code, made_by) values (v_next, v_code, auth.uid());
  return jsonb_build_object('number', v_next, 'code', v_code);
end $$;

revoke all on function public.gift_card_new() from public, anon, authenticated;
grant execute on function public.gift_card_new() to authenticated;
