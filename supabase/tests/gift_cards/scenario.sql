-- Checks for the tap gift cards (20261118000000_gift_cards.sql).
-- Each check prints ok or FAIL. Steps that are meant to be refused say how
-- many ERRORs to expect just above them.
\set ON_ERROR_STOP 0

set role authenticated;

-- A manager (Grace) makes three blank cards.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
select case when gift_cards_make(3) = 3 then 'ok' else 'FAIL' end || ' manager makes three cards';
create temp table c as select (x->>'number')::int as number, x->>'code' as code
  from jsonb_array_elements(gift_cards_list()->'cards') x;
select case when count(*) = 3 and min(number) = 1 and max(number) = 3 and bool_and(code ~ '^[a-f0-9]{32}$')
            and count(distinct code) = 3 then 'ok' else 'FAIL' end || ' numbered 1 to 3, each a different 32-letter code' from c;
grant select on c to anon;

-- Nobody reads or writes the tables directly.
\echo 'expect 2 ERRORs: no direct reading or writing'
select count(*) from gift_cards;
insert into gift_card_moves (card_id, kind, amount, balance_after) values (1, 'load', 100, 100);

-- She loads $50 on card 1.
select case when (gift_card_load((select code from c where number = 1), 50, 'GoTab tab 12')->>'balance')::numeric = 50
  then 'ok' else 'FAIL' end || ' manager loads $50';
\echo 'expect 3 ERRORs: too much at once, a negative load, fractions of a cent'
select gift_card_load((select code from c where number = 1), 600);
select gift_card_load((select code from c where number = 1), -5);
select gift_card_load((select code from c where number = 1), 1.005);

-- A guest's phone: balance only.
reset role; set role anon;
select set_config('request.jwt.claim.sub', '', false);
select case when (v->>'balance')::numeric = 50 and (v->>'number')::int = 1 and v->'moves' is null and not (v->>'staff')::boolean
  then 'ok' else 'FAIL' end || ' guest sees $50 on card #1 and no history'
  from (select gift_card_look((select code from c where number = 1)) v) x;
select case when not (gift_card_look('0123456789abcdef0123456789abcdef')->>'found')::boolean then 'ok' else 'FAIL' end || ' a made-up code finds nothing';
\echo 'expect 3 ERRORs: a guest cannot spend, load or list'
select gift_card_spend((select code from c where number = 1), 50);
select gift_card_load((select code from c where number = 1), 50);
select gift_cards_list();

-- Darrin (staff) takes $12.50 off, then tries to load.
reset role; set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000003', false);
select case when (gift_card_spend((select code from c where number = 1), 12.50, 'Two beers')->>'balance')::numeric = 37.50
  then 'ok' else 'FAIL' end || ' staff takes $12.50 off, $37.50 left';
\echo 'expect 3 ERRORs: staff cannot load, cannot spend more than is left, cannot list'
select gift_card_load((select code from c where number = 1), 20);
select gift_card_spend((select code from c where number = 1), 40);
select gift_cards_list();
select case when jsonb_array_length(v->'moves') = 2 and (v->'moves'->0->>'can_undo')::boolean
            and not (v->'moves'->1->>'can_undo')::boolean and not (v->>'can_load')::boolean
  then 'ok' else 'FAIL' end || ' staff see the history and can undo only their own'
  from (select gift_card_look((select code from c where number = 1)) v) x;
select case when gift_card_find(1) = (select code from c where number = 1) then 'ok' else 'FAIL' end || ' staff find a card by its number';

-- Undo: once, by the person who made it.
select case when (gift_card_undo((select (gift_card_look((select code from c where number = 1))->'moves'->0->>'id')::bigint))->>'balance')::numeric = 50
  then 'ok' else 'FAIL' end || ' Darrin undoes his own take-off, back to $50';
\echo 'expect 1 ERROR: the same undo twice'
select gift_card_undo((select (gift_card_look((select code from c where number = 1))->'moves'->1->>'id')::bigint));
\echo 'expect 1 ERROR: undoing somebody else''s load'
select gift_card_undo((select (gift_card_look((select code from c where number = 1))->'moves'->2->>'id')::bigint));
\echo 'expect 1 ERROR: an undo too late'
reset role;
alter table gift_card_moves disable trigger gift_card_moves_keep;
update gift_card_moves set at = at - interval '5 minutes' where card_id = (select id from gift_cards where number = 1) and kind = 'load';
alter table gift_card_moves enable trigger gift_card_moves_keep;
set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
select gift_card_undo((select (gift_card_look((select code from c where number = 1))->'moves'->2->>'id')::bigint));

-- The door login (shared, used by comics) is a guest here.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000005', false);
\echo 'expect 1 ERROR: the door login cannot spend'
select gift_card_spend((select code from c where number = 1), 5);
select case when (gift_card_look((select code from c where number = 1))->'moves') is null then 'ok' else 'FAIL' end || ' door login sees no history';

-- Two at once can't both spend the last dollars: the card is locked while one writes.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000003', false);
select case when (gift_card_spend((select code from c where number = 1), 50)->>'balance')::numeric = 0 then 'ok' else 'FAIL' end || ' spend it all, $0 left';
\echo 'expect 1 ERROR: nothing left'
select gift_card_spend((select code from c where number = 1), 0.01);

-- A lost card: switched off, its money moves to another card.
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
select gift_card_load((select code from c where number = 2), 25);
\echo 'expect 2 ERRORs: money left needs somewhere to go; staff cannot switch off'
select gift_card_switch_off(2, null, 'Lost');
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000003', false);
select gift_card_switch_off(2, 3, 'Lost');
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-000000000002', false);
select case when (gift_card_switch_off(2, 3, 'Lost')->>'moved')::numeric = 25 then 'ok' else 'FAIL' end || ' card 2 switched off, $25 moved';
select case when (gift_card_look((select code from c where number = 3))->>'balance')::numeric = 25
            and (gift_card_look((select code from c where number = 2))->>'balance')::numeric = 0
            and not (gift_card_look((select code from c where number = 2))->>'active')::boolean
            and (gift_card_look((select code from c where number = 2))->>'moved_to')::int = 3
  then 'ok' else 'FAIL' end || ' card 3 has the $25, card 2 is off and says where it went';
\echo 'expect 1 ERROR: a switched-off card cannot be spent'
select gift_card_spend((select code from c where number = 2), 1);

-- Totals: sold $50 + $25 = $75 (the moved money isn't a sale); spent $50 net of the undo; $25 still out.
select case when (r->>'sold')::numeric = 75 and (r->>'spent')::numeric = 50 then 'ok' else 'FAIL' end || ' report: $75 sold, $50 spent'
  from (select gift_card_report((now() at time zone 'America/Chicago')::date - 1, (now() at time zone 'America/Chicago')::date) r) x;
select case when (gift_cards_list()->>'outstanding')::numeric = 25 then 'ok' else 'FAIL' end || ' $25 still out on cards';

-- Nothing is ever changed or deleted, even by the service key.
reset role;
\echo 'expect 3 ERRORs: no edits or deletes of the history, no un-switching a card'
update gift_card_moves set amount = 1000 where id = 1;
delete from gift_card_moves where id = 1;
update gift_cards set active = true where number = 2;
select case when count(*) = 7 then 'ok' else 'FAIL' end || ' seven rows in the history, none lost' from gift_card_moves;
