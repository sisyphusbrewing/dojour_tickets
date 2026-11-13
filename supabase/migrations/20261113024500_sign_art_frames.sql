-- Guest pictures move too (Sam, Nov 12 2026: "the customer ones need to be
-- animated too"). sign-art has Claude draw 2-3 extra frames (each 32 rows of
-- 32 characters, same palette); the sign loops the picture and its frames.
alter table public.sign_art add column if not exists frames jsonb;

create or replace function public.sign_next()
returns json
language plpgsql
security definer
set search_path = public
as $$
declare a public.sign_art;
begin
  select * into a from public.sign_art
  where status = 'approved'
  order by last_shown nulls first, id
  limit 1
  for update skip locked;
  if not found then
    return json_build_object('id', null);
  end if;
  update public.sign_art set last_shown = now() where id = a.id;
  return json_build_object('id', a.id, 'caption', a.caption, 'palette', a.palette, 'rows', a.rows,
                           'frames', a.frames, 'kind', a.kind, 'from_name', a.from_name);
end $$;

revoke all on function public.sign_next() from public;
grant execute on function public.sign_next() to anon, authenticated;
notify pgrst, 'reload schema';
