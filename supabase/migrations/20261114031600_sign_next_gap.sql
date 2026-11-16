-- The same guest drawing comes back at most once every 10 minutes. With only
-- one or two drawings approved, the sign was showing the same one after every
-- 3rd beer (Sam, Nov 13 2026: "It keeps showing the Morgan and Grace one way
-- too much"). With nothing due, the sign just skips the guest slot.
create or replace function public.sign_next()
returns json
language plpgsql
security definer
set search_path to 'public'
as $function$
declare a public.sign_art;
begin
  select * into a from public.sign_art
  where status = 'approved'
    and (last_shown is null or last_shown < now() - interval '10 minutes')
  order by last_shown nulls first, id
  limit 1
  for update skip locked;
  if not found then
    return json_build_object('id', null);
  end if;
  update public.sign_art set last_shown = now() where id = a.id;
  return json_build_object('id', a.id, 'caption', a.caption, 'palette', a.palette, 'rows', a.rows,
                           'frames', a.frames, 'kind', a.kind, 'from_name', a.from_name);
end $function$;
