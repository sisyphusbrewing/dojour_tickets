-- VIP welcome form: a VIP / Reserved Seating buyer answers four quick
-- questions before the show (staff.sisyphusbrewing.com/vip/?t=<token>).
--
--   vip_prefs     one row per VIP door-list line (tickets.unique_id), with a
--                 private random token for the form link. vip_invite.py makes
--                 the row and emails the link; the guest's answers land here.
--                 No foreign key: the sync deletes and re-adds door-list rows,
--                 and answers must survive that.
--   vip_form_get / vip_form_save   anon RPCs the form uses; the token is the
--                 only key, so a guest only ever sees their own order.
--   door_guests   now also returns the answers, so the door list shows them
--                 next to the VIP star.

create table if not exists public.vip_prefs (
  unique_id    text primary key,
  token        text not null unique default replace(gen_random_uuid()::text, '-', ''),
  show_date    text not null,
  show_title   text not null,
  tent_name    text,
  occasion     text,
  seat_pref    text check (seat_pref in ('front', 'safe', 'any')),
  snack        text check (snack in ('salty', 'sweet', 'both', 'none')),
  answered_at  timestamptz,
  invited_at   timestamptz,
  reminded_at  timestamptz,
  created_at   timestamptz not null default now()
);
create index if not exists vip_prefs_show_idx on public.vip_prefs (show_date, show_title);

alter table public.vip_prefs enable row level security;
create policy "Allow service_role full access to vip_prefs"
  on public.vip_prefs for all to service_role using (true) with check (true);
create policy "Allow staff to read vip_prefs"
  on public.vip_prefs for select to authenticated using ((select public.is_manager()));
create policy "Managers only"
  on public.vip_prefs as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));

-- What the form shows: the show, the first name on the order, and any answers so far.
create or replace function public.vip_form_get(p_token text)
returns table (show_title text, show_date text, first_name text, tickets int,
               tent_name text, occasion text, seat_pref text, snack text, answered boolean)
language sql stable security definer set search_path = public as $$
  select p.show_title, p.show_date,
         split_part(coalesce(t.guest_name, ''), ' ', 1),
         coalesce(t.tickets, 1),
         p.tent_name, p.occasion, p.seat_pref, p.snack, p.answered_at is not null
  from public.vip_prefs p
  left join public.tickets t on t.unique_id = p.unique_id
  where p.token = p_token and length(p_token) >= 20;
$$;

create or replace function public.vip_form_save(p_token text, p_tent_name text, p_occasion text,
                                                p_seat_pref text, p_snack text)
returns boolean
language sql security definer set search_path = public as $$
  update public.vip_prefs
     set tent_name = nullif(left(btrim(coalesce(p_tent_name, '')), 40), ''),
         occasion  = nullif(left(btrim(coalesce(p_occasion, '')), 60), ''),
         seat_pref = case when p_seat_pref in ('front', 'safe', 'any') then p_seat_pref end,
         snack     = case when p_snack in ('salty', 'sweet', 'both', 'none') then p_snack end,
         answered_at = now()
   where token = p_token and length(p_token) >= 20
  returning true;
$$;

revoke all on function public.vip_form_get(text) from public;
revoke all on function public.vip_form_save(text, text, text, text, text) from public;
grant execute on function public.vip_form_get(text) to anon, authenticated;
grant execute on function public.vip_form_save(text, text, text, text, text) to anon, authenticated;

-- Door list: same as before plus the VIP answers.
drop function if exists public.door_guests(text, text);
create function public.door_guests(p_show_date text, p_show_title text)
returns table (unique_id text, guest_name text, email text, tickets int,
               checked_in_count int, ticket_type text, source text,
               vip_tent text, vip_occasion text, vip_seat text, vip_snack text)
language sql stable security definer set search_path = public as $$
  select t.unique_id, t.guest_name, t.email, t.tickets, t.checked_in_count, t.ticket_type, t.source,
         p.tent_name, p.occasion, p.seat_pref, p.snack
  from public.tickets t
  left join public.vip_prefs p on p.unique_id = t.unique_id
  where auth.uid() is not null
    and t.show_date = p_show_date and t.show_title = p_show_title
    and public.door_is_tonight(t.show_date)
  order by t.guest_name;
$$;
revoke all on function public.door_guests(text, text) from public;
grant execute on function public.door_guests(text, text) to authenticated, service_role;
