-- Guests don't wait for their drawing any more (Sam, Nov 12 2026): sign-art
-- answers right away with the new row's id and draws in the background. The
-- /sign/ page asks this until the picture is approved or turned down. It only
-- gives back what the sign itself would show, never the request or the phone.
create or replace function public.sign_status(p_id bigint)
returns json
language sql
stable
security definer
set search_path = public
as $$
  select json_build_object(
    'status', a.status,
    'note', case when a.status = 'rejected' then a.note end,
    'tamed', a.note = 'Toned down for the wall',
    'art', case when a.status = 'approved' then
      json_build_object('caption', a.caption, 'palette', a.palette, 'rows', a.rows, 'frames', a.frames) end)
  from public.sign_art a
  where a.id = p_id and a.kind = 'suggestion';
$$;

revoke all on function public.sign_status(bigint) from public;
grant execute on function public.sign_status(bigint) to anon, authenticated;
notify pgrst, 'reload schema';
