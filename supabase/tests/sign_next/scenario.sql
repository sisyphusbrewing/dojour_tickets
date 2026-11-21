-- sign_next: run on a throwaway database (see README.md). Every line should say ok.
\set QUIET on
insert into public.sign_art (kind, caption, last_shown, shows) values
  ('beer', 'OLD BEER', null, 0),                                        -- 1: never handed out
  ('suggestion', 'OLD ONE', now() - interval '5 minutes', 10),         -- 2: due again
  ('suggestion', 'TIRED ONE', now() - interval '9 minutes', 50),       -- 3: shown 50 times, not due
  ('suggestion', 'JUST SHOWN', now() - interval '1 minute', 10),        -- 4: not due
  ('suggestion', 'NEW ONE', null, 0);                                   -- 5: brand new
insert into public.sign_art (kind, caption, status) values ('suggestion', 'TAKEN DOWN', 'rejected');

select case when public.sign_next()->>'caption' = 'NEW ONE' then 'ok a brand-new drawing goes first' else 'FAIL new first' end;
select case when public.sign_next()->>'caption' = 'OLD ONE' then 'ok then the one that is due' else 'FAIL due one' end;
select case when public.sign_next()->>'id' is null then 'ok nothing due: nothing back (the sign plugs drawing instead)' else 'FAIL should be empty' end;
select case when (select shows from public.sign_art where caption = 'NEW ONE') = 1 then 'ok showings counted' else 'FAIL count' end;

-- A new drawing comes back after 2 minutes for its first 3 showings.
update public.sign_art set last_shown = now() - interval '70 seconds' where caption = 'NEW ONE';
select case when public.sign_next()->>'caption' = 'NEW ONE' then 'ok a new drawing returns after 1 minute' else 'FAIL new returns' end;
update public.sign_art set last_shown = now() - interval '3 minutes', shows = 3 where caption = 'NEW ONE';
select case when public.sign_next()->>'id' is null then 'ok after 3 showings it waits 4 minutes' else 'FAIL waits' end;

-- Fewest showings first among those due; 30 minutes once shown 40 times.
update public.sign_art set last_shown = now() - interval '11 minutes' where caption in ('TIRED ONE', 'NEW ONE');
select case when public.sign_next()->>'caption' = 'NEW ONE' then 'ok fewest showings first' else 'FAIL fewest' end;
select case when public.sign_next()->>'caption' = 'TIRED ONE' then 'ok a much-shown one after 10 minutes' else 'FAIL tired' end;
select case when not exists (select 1 from public.sign_art where kind = 'beer' and last_shown is not null)
            then 'ok old beer pictures never handed out' else 'FAIL beer' end;
