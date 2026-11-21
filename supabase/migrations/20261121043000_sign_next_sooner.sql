-- Guest drawings come back sooner (Sam, Nov 20 2026, 9:25 PM: "The sign is
-- showing the beers too much prioritize what people submit"). Same rules as
-- 20261120230000_sign_next_fresh_first.sql, shorter waits: a new drawing
-- every minute for its first 3 showings, then at least 4 minutes apart, and
-- 10 once it has been up 40 times, so nothing gets boring. The sign also
-- shows up to 3 due drawings in a row between beers (sign/pi/sign.py).
create or replace function public.sign_next()
returns json
language plpgsql
security definer
set search_path to 'public'
as $$
declare a public.sign_art;
begin
  select * into a from public.sign_art s
  where s.status = 'approved'
    and s.kind is distinct from 'beer'
    and (s.last_shown is null
         or s.last_shown < now() - case when s.shows < 3 then interval '1 minute'
                                        when s.shows < 40 then interval '4 minutes'
                                        else interval '10 minutes' end)
  order by s.last_shown is not null, s.shows, s.last_shown, s.id
  limit 1
  for update skip locked;
  if not found then
    return json_build_object('id', null);
  end if;
  update public.sign_art set last_shown = now(), shows = shows + 1 where id = a.id;
  return json_build_object('id', a.id, 'caption', a.caption, 'palette', a.palette, 'rows', a.rows,
                           'frames', a.frames, 'kind', a.kind, 'from_name', a.from_name);
end $$;
revoke all on function public.sign_next() from public;
grant execute on function public.sign_next() to anon, authenticated;
