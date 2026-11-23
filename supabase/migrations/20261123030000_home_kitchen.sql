-- The kitchen display: the Google Nest Hub in Sam and Lindsey's kitchen
-- (Sam, Nov 22 2026: "Lindsey wants more control over what shows up"; he
-- picked "a kitchen page we build" that she changes from her phone).
--
-- It rides on the "Our house" board (20261122230000_home_projects.sql): same
-- two keys, same people, same "nothing is deleted" rule. Two additions:
--   home_boards.kitchen  what the kitchen screen shows: which parts are on,
--                        and a note in big letters. Set from the phone.
--   kind 'list'          the kitchen list (groceries, to-dos). One row per
--                        thing; ticking it off sets done_at like a project.
-- The wall board and the projects page only draw project/goal/idea, so list
-- rows never show up there.

alter table public.home_boards add column if not exists kitchen jsonb not null default '{}'::jsonb;

alter table public.home_items drop constraint if exists home_items_kind_check;
alter table public.home_items add constraint home_items_kind_check
  check (kind in ('project', 'goal', 'idea', 'list'));

-- Everything the kitchen screen and its phone page draw: the house board
-- (list rows included) plus the kitchen settings.
create or replace function public.kitchen_board(k text) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare b record; v jsonb;
begin
  select * into b from public.home_board_for(k);
  if b.board is null then return null; end if;
  v := public.home_board(k);
  return v || jsonb_build_object('kitchen', (select kitchen from public.home_boards where id = b.board));
end $$;
grant execute on function public.kitchen_board(text) to anon, authenticated;

-- Changes from the kitchen phone page. op 'settings' takes
--   {show: {clock, weather, calendar, list, note, house, shows: true/false}, note: text}
-- and keeps only those keys. Anything else is handed to home_board_edit
-- (add_item with kind 'list', done_item, remove_item, restore_item, ...).
create or replace function public.kitchen_edit(k text, op text, args jsonb default '{}'::jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare b record; v_show jsonb := '{}'::jsonb; v_key text; v_note text;
begin
  select * into b from public.home_board_for(k);
  if b.board is null or not b.can_edit then raise exception 'This link can''t change the kitchen screen.'; end if;
  if op = 'settings' then
    if jsonb_typeof(args->'show') = 'object' then
      foreach v_key in array array['clock', 'weather', 'calendar', 'list', 'note', 'house', 'shows'] loop
        if jsonb_typeof(args->'show'->v_key) = 'boolean' then
          v_show := v_show || jsonb_build_object(v_key, args->'show'->v_key);
        end if;
      end loop;
      update public.home_boards set kitchen = jsonb_set(kitchen, '{show}', coalesce(kitchen->'show', '{}'::jsonb) || v_show) where id = b.board;
    end if;
    if args ? 'note' then
      v_note := nullif(btrim(coalesce(args->>'note', '')), '');
      if length(v_note) > 280 then raise exception 'Keep the note under 280 letters so it fits.'; end if;
      update public.home_boards set kitchen = kitchen || jsonb_build_object('note', v_note, 'note_at', now()) where id = b.board;
    end if;
  else
    if op = 'add_item' and coalesce(args->>'kind', '') <> 'list' then raise exception 'Unknown change.'; end if;
    perform public.home_board_edit(k, op, args);
  end if;
  return public.kitchen_board(k);
end $$;
grant execute on function public.kitchen_edit(text, text, jsonb) to anon, authenticated;
