-- Our house: house projects, goals and ideas that Sam and Lindsey keep
-- together, shown on the Apolosign wall board at home and edited from either
-- phone (Sam, Nov 22 2026: "Where Lindsey and I can collaborate on house
-- projects and/or goals and ideas", e.g. the front porch redo "in order of
-- what we need"; "Lindsey likes graphical interactive stuff").
--
-- Nobody logs in. The board has two keys, kept only here in the database:
--   view_key  the wall board reads with it (the key already in its kiosk URL)
--   edit_key  the phone link /home/projects/?k=<edit_key>; whoever has it can edit
-- Who is Sam and who is Lindsey is the board's `people` list, so their names
-- are not written in this public repo. Nothing is ever deleted: a removed
-- project or step is marked removed and can be put back.

create table if not exists public.home_boards (
  id         text primary key,
  view_key   text not null unique default encode(extensions.gen_random_bytes(9), 'hex'),
  edit_key   text not null unique default encode(extensions.gen_random_bytes(12), 'hex'),
  people     text[] not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists public.home_items (
  id         uuid primary key default gen_random_uuid(),
  board      text not null references public.home_boards(id),
  kind       text not null default 'project' check (kind in ('project', 'goal', 'idea')),
  title      text not null check (length(title) between 1 and 120),
  note       text check (length(note) <= 2000),
  emoji      text check (length(emoji) <= 16),
  color      text check (color ~ '^#[0-9a-fA-F]{6}$'),
  position   double precision not null default 0,
  added_by   text,
  done_at    timestamptz,
  removed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists home_items_board on public.home_items (board, kind, position);

create table if not exists public.home_steps (
  id         uuid primary key default gen_random_uuid(),
  item_id    uuid not null references public.home_items(id),
  title      text not null check (length(title) between 1 and 160),
  position   double precision not null default 0,
  added_by   text,
  done_at    timestamptz,
  done_by    text,
  removed_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists home_steps_item on public.home_steps (item_id, position);

alter table public.home_boards enable row level security;
alter table public.home_items enable row level security;
alter table public.home_steps enable row level security;
-- No policies: only the two functions below (and the service key) reach these.

insert into public.home_boards (id) values ('home') on conflict do nothing;

-- Which board a key opens, and whether it may edit. Null for a wrong key.
create or replace function public.home_board_for(k text, out board text, out can_edit boolean)
language sql stable security definer set search_path = public as $$
  select id, edit_key = k from public.home_boards
  where k is not null and length(k) >= 6 and (view_key = k or edit_key = k)
$$;
revoke all on function public.home_board_for(text) from public, anon, authenticated;

-- Everything the wall and the phone page draw: projects, goals and ideas in
-- order, each with its steps in order. Done ones stay (the page decides how
-- long to show them); removed ones are left out.
create or replace function public.home_board(k text) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare b record;
begin
  select * into b from public.home_board_for(k);
  if b.board is null then return null; end if;
  return jsonb_build_object(
    'can_edit', b.can_edit,
    'people', (select to_jsonb(people) from public.home_boards where id = b.board),
    'items', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', i.id, 'kind', i.kind, 'title', i.title, 'note', i.note, 'emoji', i.emoji, 'color', i.color,
        'added_by', i.added_by, 'done_at', i.done_at, 'created_at', i.created_at, 'updated_at', i.updated_at,
        'steps', coalesce((
          select jsonb_agg(jsonb_build_object('id', s.id, 'title', s.title, 'done_at', s.done_at,
                                              'done_by', s.done_by, 'added_by', s.added_by)
                           order by s.position, s.created_at)
          from public.home_steps s where s.item_id = i.id and s.removed_at is null), '[]'::jsonb))
        order by i.position, i.created_at)
      from public.home_items i where i.board = b.board and i.removed_at is null), '[]'::jsonb));
end $$;
grant execute on function public.home_board(text) to anon, authenticated;

-- Every change from the phone page. op is one of:
--   add_item {kind,title,note,emoji,color,who}     update_item {id,title,note,emoji,color,kind}
--   order_items {ids:[...]}                         done_item {id,done,who}
--   remove_item {id}   restore_item {id}
--   add_step {item_id,title,who}   update_step {id,title}   order_steps {item_id,ids:[...]}
--   done_step {id,done,who}   remove_step {id}   restore_step {id}
-- Returns the whole board again, so the page redraws from the truth.
create or replace function public.home_board_edit(k text, op text, args jsonb default '{}'::jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  b record; v_id uuid; v_item uuid; v_pos double precision; v_n int;
  v_who text := nullif(left(btrim(coalesce(args->>'who', '')), 40), '');
begin
  select * into b from public.home_board_for(k);
  if b.board is null or not b.can_edit then raise exception 'This link can''t change the board.'; end if;

  -- Anything that names an item or step must be on this board.
  if args ? 'id' and op like '%_item' and op <> 'add_item' then
    v_id := (args->>'id')::uuid;
    if not exists (select 1 from public.home_items where id = v_id and board = b.board) then raise exception 'Not found.'; end if;
  elsif args ? 'id' and op like '%_step' and op <> 'add_step' then
    v_id := (args->>'id')::uuid;
    if not exists (select 1 from public.home_steps s join public.home_items i on i.id = s.item_id
                   where s.id = v_id and i.board = b.board) then raise exception 'Not found.'; end if;
  end if;
  if args ? 'item_id' then
    v_item := (args->>'item_id')::uuid;
    if not exists (select 1 from public.home_items where id = v_item and board = b.board) then raise exception 'Not found.'; end if;
  end if;

  if op = 'add_item' then
    select count(*) into v_n from public.home_items where board = b.board and removed_at is null;
    if v_n >= 300 then raise exception 'The board is full. Clear some done ones first.'; end if;
    -- New ones go to the end of their list.
    select coalesce(max(position), 0) + 1 into v_pos from public.home_items
      where board = b.board and kind = coalesce(args->>'kind', 'project');
    insert into public.home_items (board, kind, title, note, emoji, color, position, added_by)
    values (b.board, coalesce(args->>'kind', 'project'), btrim(args->>'title'), nullif(btrim(coalesce(args->>'note', '')), ''),
            nullif(args->>'emoji', ''), nullif(args->>'color', ''), v_pos, v_who);
  elsif op = 'update_item' then
    update public.home_items set
      title = coalesce(nullif(btrim(args->>'title'), ''), title),
      note  = case when args ? 'note' then nullif(btrim(coalesce(args->>'note', '')), '') else note end,
      emoji = case when args ? 'emoji' then nullif(args->>'emoji', '') else emoji end,
      color = case when args ? 'color' then nullif(args->>'color', '') else color end,
      kind  = coalesce(args->>'kind', kind),
      updated_at = now()
    where id = v_id;
  elsif op = 'order_items' then
    update public.home_items i set position = o.n, updated_at = now()
    from jsonb_array_elements_text(args->'ids') with ordinality o(id, n)
    where i.id = o.id::uuid and i.board = b.board;
  elsif op = 'done_item' then
    update public.home_items set done_at = case when (args->>'done')::boolean then now() end, updated_at = now() where id = v_id;
  elsif op = 'remove_item' then
    update public.home_items set removed_at = now(), updated_at = now() where id = v_id;
  elsif op = 'restore_item' then
    update public.home_items set removed_at = null, updated_at = now() where id = v_id;
  elsif op = 'add_step' then
    select count(*) into v_n from public.home_steps where item_id = v_item and removed_at is null;
    if v_n >= 60 then raise exception 'That''s a lot of steps. Split it into two projects?'; end if;
    select coalesce(max(position), 0) + 1 into v_pos from public.home_steps where item_id = v_item;
    insert into public.home_steps (item_id, title, position, added_by) values (v_item, btrim(args->>'title'), v_pos, v_who);
    update public.home_items set updated_at = now() where id = v_item;
  elsif op = 'update_step' then
    update public.home_steps set title = coalesce(nullif(btrim(args->>'title'), ''), title) where id = v_id;
  elsif op = 'order_steps' then
    update public.home_steps s set position = o.n
    from jsonb_array_elements_text(args->'ids') with ordinality o(id, n)
    where s.id = o.id::uuid and s.item_id = v_item;
  elsif op = 'done_step' then
    update public.home_steps set done_at = case when (args->>'done')::boolean then now() end,
                                 done_by = case when (args->>'done')::boolean then v_who end where id = v_id;
  elsif op = 'remove_step' then
    update public.home_steps set removed_at = now() where id = v_id;
  elsif op = 'restore_step' then
    update public.home_steps set removed_at = null where id = v_id;
  else
    raise exception 'Unknown change.';
  end if;

  return public.home_board(k);
end $$;
grant execute on function public.home_board_edit(text, text, jsonb) to anon, authenticated;
