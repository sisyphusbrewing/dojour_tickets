-- The sign shows who drew each picture: "BY JAKE" under it (Sam, Nov 12 2026,
-- "we need people to be able to put their names in"). The name comes from the
-- optional name box on /sign/, already checked for rude words by sign-art.
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
                           'kind', a.kind, 'from_name', a.from_name);
end $$;

revoke all on function public.sign_next() from public;
grant execute on function public.sign_next() to anon, authenticated;
