-- Which guest drawing the front bar sign shows next (Sam, Nov 20 2026:
-- "Prioritize getting drawings", "Be adaptable so new content is preferred",
-- "But don't let something get shown so many times it gets boring").
--
--  * A drawing nobody has seen yet goes up first, right away.
--  * A new drawing comes back every 2 minutes for its first 3 showings, so
--    the guest who asked for it sees it while they're still at the bar.
--  * After that it waits at least 10 minutes between showings, and once it
--    has been up 40 times, 30 minutes. Fewest showings go first.
--  * When nothing is due, the sign gets nothing back and puts up "draw on
--    this sign" instead (sign/pi/sign.py). There's no "show the only one
--    again" any more: that is how one drawing got boring.
--  * The old beer pictures (kind 'beer') are skipped; the sign draws beers
--    itself from the menu, and handing one out wasted the guest's turn.
-- Replaces 20261115223500_sign_next_no_wait.sql (and the temporary hold on
-- one prompt: that drawing has since been taken down).
alter table public.sign_art add column if not exists shows integer not null default 0;

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
         or s.last_shown < now() - case when s.shows < 3 then interval '2 minutes'
                                        when s.shows < 40 then interval '10 minutes'
                                        else interval '30 minutes' end)
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
