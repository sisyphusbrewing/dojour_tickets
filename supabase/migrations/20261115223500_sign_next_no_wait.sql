-- Guest drawings take turns with no waiting time (Sam, Nov 15 2026: "Waiting
-- 10 minutes between showings is insane"). The sign shows the drawing that
-- has gone longest without being shown, and never the same drawing twice in
-- a row when there is more than one. Replaces the 10-minute gap from
-- 20261114031600_sign_next_gap.sql.
create or replace function public.sign_next()
returns json
language plpgsql
security definer
set search_path to 'public'
as $$
declare a public.sign_art;
begin
  select * into a from public.sign_art
  where status = 'approved'
    and id is distinct from (select id from public.sign_art
                             where status = 'approved' and last_shown is not null
                             order by last_shown desc limit 1)
  order by last_shown nulls first, id
  limit 1
  for update skip locked;
  if not found then  -- only one drawing: show it again
    select * into a from public.sign_art where status = 'approved'
    order by last_shown nulls first, id limit 1 for update skip locked;
  end if;
  if not found then
    return json_build_object('id', null);
  end if;
  update public.sign_art set last_shown = now() where id = a.id;
  return json_build_object('id', a.id, 'caption', a.caption, 'palette', a.palette, 'rows', a.rows,
                           'frames', a.frames, 'kind', a.kind, 'from_name', a.from_name);
end $$;
