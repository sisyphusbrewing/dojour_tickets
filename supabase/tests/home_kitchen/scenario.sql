-- Kitchen display: run on a throwaway database after the home_projects stub and
-- both migrations (see README.md). Every line should say ok.
\set QUIET on
update public.home_boards set view_key = 'viewkey1', edit_key = 'editkey123456', people = '{A,B}' where id = 'home';
set role anon;
select case when public.kitchen_board('nope') is null then 'ok wrong key sees nothing' else 'FAIL wrong key' end;
select case when public.kitchen_board('viewkey1')->'kitchen' = '{}'::jsonb then 'ok wall key reads settings' else 'FAIL read' end;
do $$ begin perform public.kitchen_edit('viewkey1', 'settings', '{"note":"x"}'); raise notice 'FAIL wall key changed the kitchen';
exception when others then raise notice 'ok wall key cannot change the kitchen'; end $$;
select case when public.kitchen_edit('editkey123456', 'settings', '{"show":{"shows":true,"weather":false,"bogus":true,"clock":"yes"}}')->'kitchen'->'show'
  = '{"shows":true,"weather":false}'::jsonb then 'ok only known switches are kept' else 'FAIL switches' end;
select case when public.kitchen_edit('editkey123456', 'settings', '{"show":{"weather":true}}')->'kitchen'->'show'
  = '{"shows":true,"weather":true}'::jsonb then 'ok switches merge' else 'FAIL merge' end;
select case when public.kitchen_edit('editkey123456', 'settings', '{"note":"  Pizza night  "}')->'kitchen'->>'note' = 'Pizza night' then 'ok note saved' else 'FAIL note' end;
select case when public.kitchen_edit('editkey123456', 'settings', '{"note":""}')->'kitchen'->>'note' is null then 'ok note taken down' else 'FAIL clear note' end;
do $$ begin perform public.kitchen_edit('editkey123456', 'settings', jsonb_build_object('note', repeat('x', 281))); raise notice 'FAIL long note';
exception when others then raise notice 'ok long note refused'; end $$;
select case when (select count(*) from jsonb_array_elements(public.kitchen_edit('editkey123456', 'add_item', '{"kind":"list","title":"Milk","who":"A"}')->'items') x
  where x->>'kind' = 'list') = 1 then 'ok list item added' else 'FAIL list add' end;
do $$ begin perform public.kitchen_edit('editkey123456', 'add_item', '{"kind":"project","title":"x"}'); raise notice 'FAIL kitchen page added a project';
exception when others then raise notice 'ok kitchen page adds list items only'; end $$;
create temp table t as select (x->>'id')::uuid id from jsonb_array_elements(public.kitchen_board('viewkey1')->'items') x where x->>'kind' = 'list';
select case when (select x->>'done_at' from jsonb_array_elements(public.kitchen_edit('editkey123456', 'done_item', jsonb_build_object('id', (select id from t), 'done', true))->'items') x
  where (x->>'id')::uuid = (select id from t)) is not null then 'ok list item ticked off' else 'FAIL tick' end;
select case when public.kitchen_edit('editkey123456', 'remove_item', jsonb_build_object('id', (select id from t)))->'items' = '[]'::jsonb then 'ok removed item hidden' else 'FAIL remove' end;
reset role;
select case when (select count(*) from public.home_items) = 1 then 'ok nothing deleted' else 'FAIL deleted' end;
