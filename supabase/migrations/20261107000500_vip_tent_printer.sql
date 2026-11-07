-- Office PC prints each show's VIP table tents by itself, 90 minutes before
-- showtime (Sam, Nov 6 2026: "make it work for future shows too").
--
--   vip_printers      sha256 of the office PC's private key (no raw keys stored)
--   vip_tent_prints   which showtimes have been printed, so each prints once
--   vip_tents_for_day(key, 'Sat, Nov 7')   every VIP tent for that day's shows:
--                     the guest's tent name or the name on the order, occasion,
--                     and whether that showtime already printed
--   vip_tents_printed(key, show_date, show_title)   mark a showtime printed
--
-- The PC script lives in av/vip-tents/print-vip-tents.ps1.

create table if not exists public.vip_printers (
  key_hash text primary key,
  label    text,
  created_at timestamptz not null default now()
);
create table if not exists public.vip_tent_prints (
  show_date  text not null,
  show_title text not null,
  printed_at timestamptz not null default now(),
  primary key (show_date, show_title)
);
alter table public.vip_printers enable row level security;
alter table public.vip_tent_prints enable row level security;
create policy "Allow service_role full access to vip_printers" on public.vip_printers for all to service_role using (true) with check (true);
create policy "Allow service_role full access to vip_tent_prints" on public.vip_tent_prints for all to service_role using (true) with check (true);
create policy "Managers only" on public.vip_printers as restrictive for all to authenticated using ((select public.is_manager())) with check ((select public.is_manager()));
create policy "Managers only" on public.vip_tent_prints as restrictive for all to authenticated using ((select public.is_manager())) with check ((select public.is_manager()));

create or replace function public.vip_tents_for_day(p_key text, p_day text)
returns table (show_date text, show_title text, tent_name text, occasion text, printed boolean)
language sql stable security definer set search_path = public, extensions as $$
  select t.show_date, t.show_title,
         coalesce(nullif(p.tent_name, ''), t.guest_name),
         p.occasion,
         exists (select 1 from public.vip_tent_prints x where x.show_date = t.show_date and x.show_title = t.show_title)
  from public.tickets t
  left join public.vip_prefs p on p.unique_id = t.unique_id
  where exists (select 1 from public.vip_printers k where k.key_hash = encode(digest(p_key, 'sha256'), 'hex'))
    and t.show_date like p_day || ' •%'
    and t.ticket_type ~* 'vip|premium|reserved'
    and t.guest_name !~* '^(shopify sales|website hold)'
  order by t.show_date, 3;
$$;

create or replace function public.vip_tents_printed(p_key text, p_show_date text, p_show_title text)
returns boolean
language sql security definer set search_path = public, extensions as $$
  insert into public.vip_tent_prints (show_date, show_title)
  select p_show_date, p_show_title
  where exists (select 1 from public.vip_printers k where k.key_hash = encode(digest(p_key, 'sha256'), 'hex'))
  on conflict do nothing
  returning true;
$$;

revoke all on function public.vip_tents_for_day(text, text) from public;
revoke all on function public.vip_tents_printed(text, text, text) from public;
grant execute on function public.vip_tents_for_day(text, text) to anon, authenticated;
grant execute on function public.vip_tents_printed(text, text, text) to anon, authenticated;

-- The office PC (DESKTOP-8QOGQGK); its key is in C:\Sisyphus\vip-tents\key.txt.
insert into public.vip_printers (key_hash, label)
values ('f7b157b5e68ba672eeea10abfe392266291c5827be627ecccf3110647d4f2fad', 'Office PC DESKTOP-8QOGQGK')
on conflict do nothing;
-- Both Nov 6 shows were printed by hand that night.
insert into public.vip_tent_prints (show_date, show_title) values
  ('Fri, Nov 6 • 7:00 PM', 'Michael Longfellow'), ('Fri, Nov 6 • 9:00 PM', 'Michael Longfellow')
on conflict do nothing;
