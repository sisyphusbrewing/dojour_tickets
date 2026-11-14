-- Guests can fix their own drawing (Sam, Nov 13 2026: "Let's let them have the
-- ability to correct it if they don't like it"). fixes counts how many times
-- (2 at most). When a fix can't go up, the first picture stays and the note
-- starts "Fix not used:", which sign_status passes back as "kept".
alter table public.sign_art add column if not exists fixes int not null default 0;

create or replace function public.sign_status(p_id bigint)
returns json
language sql
stable security definer
set search_path to 'public'
as $function$
  select json_build_object(
    'status', a.status,
    'note', case when a.status = 'rejected' then a.note end,
    'tamed', a.note = 'Toned down for the wall',
    'kept', case when a.note like 'Fix not used:%' then substr(a.note, 15) end,
    'fixes', a.fixes,
    'art', case when a.status = 'approved' then
      json_build_object('caption', a.caption, 'palette', a.palette, 'rows', a.rows, 'frames', a.frames) end)
  from public.sign_art a
  where a.id = p_id and a.kind = 'suggestion';
$function$;
