-- Our house board: run on a throwaway database (see README.md). Every line should say ok.
\set QUIET on
update public.home_boards set view_key = 'viewkey1', edit_key = 'editkey123456', people = '{A,B}' where id = 'home';
set role anon;
select case when public.home_board('nope') is null then 'ok wrong key sees nothing' else 'FAIL wrong key' end;
select case when public.home_board('viewkey1')->>'can_edit' = 'false' then 'ok wall key reads only' else 'FAIL wall key' end;
do $$ begin perform public.home_board_edit('viewkey1', 'add_item', '{"title":"x"}'); raise notice 'FAIL wall key edited';
exception when others then raise notice 'ok wall key cannot edit'; end $$;
select case when jsonb_array_length(public.home_board_edit('editkey123456', 'add_item',
  '{"kind":"project","title":"Front porch","emoji":"🏡","color":"#4f6d8c","who":"A"}')->'items') = 1 then 'ok phone adds a project' else 'FAIL add' end;
create temp table t as select (public.home_board('viewkey1')->'items'->0->>'id')::uuid as id;
select public.home_board_edit('editkey123456', 'add_step', jsonb_build_object('item_id', (select id from t), 'title', s, 'who', 'B')) is not null
from unnest(array['Pick paint','Scrape','Prime','Paint']) s;
select case when (select array_agg(x->>'title') from jsonb_array_elements(public.home_board('viewkey1')->'items'->0->'steps') x)
  = array['Pick paint','Scrape','Prime','Paint'] then 'ok steps keep their order' else 'FAIL step order' end;
create temp table st as select array_agg((x->>'id')::uuid) ids from jsonb_array_elements(public.home_board('viewkey1')->'items'->0->'steps') x;
select public.home_board_edit('editkey123456', 'order_steps', jsonb_build_object('item_id', (select id from t),
  'ids', jsonb_build_array((select ids[2] from st), (select ids[1] from st), (select ids[3] from st), (select ids[4] from st)))) is not null;
select case when public.home_board('viewkey1')->'items'->0->'steps'->0->>'title' = 'Scrape' then 'ok steps reorder' else 'FAIL reorder' end;
select public.home_board_edit('editkey123456', 'done_step', jsonb_build_object('id', (select ids[2] from st), 'done', true, 'who', 'A')) is not null;
select case when public.home_board('viewkey1')->'items'->0->'steps'->0->>'done_by' = 'A' then 'ok step checked off by A' else 'FAIL done' end;
select public.home_board_edit('editkey123456', 'remove_step', jsonb_build_object('id', (select ids[4] from st))) is not null;
select case when jsonb_array_length(public.home_board('viewkey1')->'items'->0->'steps') = 3 then 'ok removed step hidden' else 'FAIL remove' end;
select public.home_board_edit('editkey123456', 'restore_step', jsonb_build_object('id', (select ids[4] from st))) is not null;
select case when jsonb_array_length(public.home_board('viewkey1')->'items'->0->'steps') = 4 then 'ok removed step comes back' else 'FAIL restore' end;
do $$ begin perform public.home_board_edit('editkey123456', 'done_step', jsonb_build_object('id', gen_random_uuid(), 'done', true)); raise notice 'FAIL stranger id';
exception when others then raise notice 'ok unknown step refused'; end $$;
do $$ begin perform public.home_board_edit('editkey123456', 'add_item', '{"title":""}'); raise notice 'FAIL empty title';
exception when others then raise notice 'ok empty title refused'; end $$;
do $$ begin perform public.home_board_edit('editkey123456', 'add_item', '{"title":"x","color":"red;"}'); raise notice 'FAIL bad color';
exception when others then raise notice 'ok bad color refused'; end $$;
do $$ begin insert into public.home_items (board, title) values ('home', 'sneaky'); raise notice 'FAIL anon wrote the table';
exception when others then raise notice 'ok tables closed to the public'; end $$;
select case when public.home_board_edit('editkey123456', 'add_item', '{"kind":"idea","title":"Hot tub"}')->'items'->1->>'kind' = 'idea' then 'ok idea added' else 'FAIL idea' end;
