-- Reorder buttons on the Supplies page (Sam, Nov 17 2026: "We are going to
-- order on a regular basis ... it would be nice to have buttons to order stuff
-- like that, Pretzels (which we need 1 box of each flavor of)", then syrups,
-- seltzer kegs, beef jerky, sodas, Liquid Death, kombucha).
--
-- Every one of those comes from a vendor Sam orders from by email, so a button
-- is "the usual order email to that vendor". A manager taps Pretzels, sees the
-- exact email with the usual amounts, changes a number if needed and taps
-- Send. That writes a row to supply_orders; the "Low supplies" action
-- (supply_notify.py), which the page starts right away, emails it to the
-- vendor with sam@ and booking@ copied and replies going to Sam.
--
-- supply_reorders  one row per button: who it goes to and the usual lines.
-- supply_orders    one row per order sent (or waiting to be sent). Never
--                  deleted, so "last ordered Nov 17 by Grace" is always true.
--
-- The email text is built here (reorder_email_body), not in the page, so the
-- preview and what the vendor gets are the same words. Only managers (and
-- the owner) can send; staff can see the buttons and when each was last sent.

create table if not exists public.supply_reorders (
  id         uuid primary key default gen_random_uuid(),
  label      text not null,                    -- the button: "Pretzels"
  vendor     text not null,                    -- "Von Hanson's Snacks"
  to_email   text not null,
  greeting   text not null,                    -- "Hey Andy,"
  intro      text not null,                    -- "Can we get a delivery at Sisyphus this week?"
  lines      jsonb not null default '[]',      -- [{"qty":6,"unit":"cases","item":"Spring Grove Root Beer"}]
  subject    text not null,
  notes      text,                             -- shown on the page only: "Delivers Fridays; order by Wed 7 PM"
  sort       integer not null default 100,
  active     boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.supply_orders (
  id          uuid primary key default gen_random_uuid(),
  reorder_id  uuid not null references public.supply_reorders(id),
  to_email    text not null,
  subject     text not null,
  body        text not null,
  lines       jsonb not null,
  ordered_by  uuid,                             -- the login that pressed Send
  ordered_by_name text,
  ordered_at  timestamptz not null default now(),
  status      text not null default 'queued' check (status in ('queued', 'sent', 'failed')),
  sent_at     timestamptz,
  error       text
);
create index if not exists supply_orders_reorder_idx on public.supply_orders (reorder_id, ordered_at desc);
create index if not exists supply_orders_queued_idx on public.supply_orders (status) where status = 'queued';

create trigger supply_reorders_set_updated_at
  before update on public.supply_reorders
  for each row execute function public.set_updated_at();

alter table public.supply_reorders enable row level security;
alter table public.supply_orders enable row level security;

-- Supabase hands every new table to the website logins with full rights.
-- Take them back: staff read, and orders are only written through
-- place_reorder() below (or by the sending script, which uses the service key).
revoke all on public.supply_reorders, public.supply_orders from anon, authenticated;
grant select on public.supply_reorders, public.supply_orders to authenticated;
grant all on public.supply_reorders, public.supply_orders to service_role;

create policy "Staff read reorder buttons" on public.supply_reorders
  for select to authenticated using ((select public.is_staff()));
create policy "Staff read orders" on public.supply_orders
  for select to authenticated using ((select public.is_staff()));
create policy "Service role reorders" on public.supply_reorders
  for all to service_role using (true) with check (true);
create policy "Service role orders" on public.supply_orders
  for all to service_role using (true) with check (true);

-- The words of the email. One line per item with a count above zero:
--   Hey Andy,
--
--   Can we get a delivery at Sisyphus this week? We need:
--   6 cases Spring Grove Root Beer
--   ...
--   (the note, if one was typed)
--
--   Thanks much!
--   Sam
create or replace function public.reorder_email_body(
  p_greeting text, p_intro text, p_lines jsonb, p_note text, p_signer text)
returns text language sql immutable set search_path = public as $$
  select concat_ws(E'\n',
    p_greeting, '',
    p_intro,
    (select string_agg(
              concat_ws(' ', trim_scale((l->>'qty')::numeric)::text,
                        nullif(trim(l->>'unit'), ''), trim(l->>'item')),
              E'\n' order by o)
       from jsonb_array_elements(coalesce(p_lines, '[]')) with ordinality as x(l, o)
      where coalesce((l->>'qty')::numeric, 0) > 0),
    case when nullif(trim(p_note), '') is not null then E'\n' || trim(p_note) end,
    '', 'Thanks much!', p_signer)
$$;

-- Who signs the email: Sam's own login signs "Sam"; anyone else signs their
-- name and "Sisyphus", so the vendor knows it came from the club.
create or replace function public.reorder_signer()
returns text language sql stable security definer set search_path = public, auth as $$
  select case when public.is_owner() then 'Sam'
              else coalesce(public.schedule_name(auth.uid()), 'Sisyphus') || E'\nSisyphus' end
$$;

-- What the page shows before Send: the exact email.
create or replace function public.reorder_preview(p_reorder uuid, p_lines jsonb default null, p_note text default null)
returns table (to_email text, subject text, body text)
language sql stable security definer set search_path = public as $$
  select r.to_email, r.subject,
         public.reorder_email_body(r.greeting, r.intro, coalesce(p_lines, r.lines), p_note, public.reorder_signer())
    from public.supply_reorders r
   where r.id = p_reorder and r.active and public.is_staff()
$$;

-- Send. Managers only. Refuses an empty order, and refuses the same button
-- twice inside three days unless p_again is true (the page asks "Send it
-- again?"), so two people tapping Pretzels on the same night order once.
create or replace function public.place_reorder(
  p_reorder uuid, p_lines jsonb default null, p_note text default null, p_again boolean default false)
returns public.supply_orders
language plpgsql security definer set search_path = public as $$
declare
  r public.supply_reorders;
  v_lines jsonb;
  v_last timestamptz;
  v_row public.supply_orders;
begin
  if not public.is_manager() then
    raise exception 'Only a manager can send an order.';
  end if;
  select * into r from public.supply_reorders where id = p_reorder and active;
  if not found then raise exception 'That order button is gone.'; end if;

  -- Counts can change; names can't. Each line keeps the button's item and
  -- unit and takes only the new count, so nobody can turn the pretzel email
  -- into something else.
  select coalesce(jsonb_agg(jsonb_build_object(
           'qty', greatest(0, coalesce((select (n->>'qty')::numeric
                                          from jsonb_array_elements(coalesce(p_lines, '[]')) n
                                         where n->>'item' = b->>'item' limit 1),
                                       (b->>'qty')::numeric)),
           'unit', b->'unit', 'item', b->'item') order by o), '[]')
    into v_lines
    from jsonb_array_elements(r.lines) with ordinality as x(b, o);

  if not exists (select 1 from jsonb_array_elements(v_lines) l where (l->>'qty')::numeric > 0) then
    raise exception 'Nothing to order: every count is zero.';
  end if;
  if length(coalesce(p_note, '')) > 500 then
    raise exception 'Keep the note under 500 characters.';
  end if;

  select max(ordered_at) into v_last from public.supply_orders
   where reorder_id = r.id and status <> 'failed';
  if v_last is not null and v_last > now() - interval '3 days' and not coalesce(p_again, false) then
    raise exception 'ALREADY_SENT %', to_char(v_last at time zone 'America/Chicago', 'Dy Mon FMDD at FMHH12:MI AM');
  end if;

  insert into public.supply_orders (reorder_id, to_email, subject, body, lines, ordered_by, ordered_by_name)
  values (r.id, r.to_email, r.subject,
          public.reorder_email_body(r.greeting, r.intro, v_lines, p_note, public.reorder_signer()),
          v_lines, auth.uid(), public.schedule_name(auth.uid()))
  returning * into v_row;
  return v_row;
end $$;

revoke all on function public.reorder_preview(uuid, jsonb, text) from public, anon;
revoke all on function public.place_reorder(uuid, jsonb, text, boolean) from public, anon;
grant execute on function public.reorder_preview(uuid, jsonb, text) to authenticated;
grant execute on function public.place_reorder(uuid, jsonb, text, boolean) to authenticated;

-- The buttons, with the amounts from Sam's last order to each vendor
-- (sam@ Gmail, Sep to Nov 2026). Managers change a count before sending.
insert into public.supply_reorders (label, vendor, to_email, greeting, intro, lines, subject, notes, sort)
select * from (values
  ('Pretzels', 'Von Hanson''s Snacks', 'businessoffice@vonhansonssnacks.com',
   'Hi there,', 'Can we get a snack order delivered to Sisyphus this week?',
   '[{"qty":1,"unit":"case of each","item":"pretzel flavor"}]'::jsonb,
   'Sisyphus snack order', 'Delivers the same week. Sam''s usual: one case of each pretzel.', 10),
  ('Beef jerky', 'Ye Olde Butcher Shoppe', 'kevin@yeoldebutchershoppe.com',
   'Hey Kevin,', 'Can we get a jerky delivery at Sisyphus?',
   '[{"qty":1,"unit":"order of each","item":"jerky flavor (we are good on sticks)"}]'::jsonb,
   'Sisyphus jerky order', 'Kevin delivers about a week later.', 20),
  ('Sodas & Liquid Death', 'Capitol Beverage', 'amiska@capitolbeverage.com',
   'Hey Andy,', 'Can we get a delivery at Sisyphus this week? We need:',
   '[{"qty":6,"unit":"cases","item":"Spring Grove Root Beer"},
     {"qty":4,"unit":"cases","item":"Spring Grove Orange"},
     {"qty":3,"unit":"cases","item":"Spring Grove Strawberry"},
     {"qty":3,"unit":"cases","item":"Spring Grove Lemon Sour"},
     {"qty":6,"unit":"cases","item":"Orange Liquid Death"},
     {"qty":6,"unit":"cases","item":"Lime Liquid Death"}]'::jsonb,
   'Sisyphus order', 'Order by Wednesday 7 PM for Friday delivery. Set a count to 0 to skip it.', 30),
  ('Syrups', 'Sweet Haven Tonics', 'leah@sweethaventonics.com',
   'Hi Leah,', 'Can we get another order? All in liters:',
   '[{"qty":6,"unit":"","item":"Blueberry Mint"},
     {"qty":6,"unit":"","item":"Lemon Basil & Lavender"},
     {"qty":3,"unit":"","item":"Apple Thyme"},
     {"qty":3,"unit":"","item":"winter flavor of your choice"}]'::jsonb,
   'Sisyphus Reorder', 'About $35 a liter, invoiced to Sam.', 40),
  ('Seltzer kegs', 'ABV Technology', 'Order@abvtechnology.com',
   'Hi ABV team,', 'Can we get a quote and a fill for:',
   '[{"qty":5,"unit":"kegs","item":"Sisyphus 10% seltzer, flat (uncarbonated)"}]'::jsonb,
   'Sisyphus seltzer order', 'They quote first. Drop empty kegs Mon to Fri, 9 to 4.', 50),
  ('Kombucha', 'J''s NA Distribution', 'orders@jsnadistribution.com',
   'Hi Seth,', 'Can we get a kombucha delivery at Sisyphus?',
   '[{"qty":12,"unit":"cases","item":"Raspberry"},
     {"qty":12,"unit":"cases","item":"Ginger"}]'::jsonb,
   'Sisyphus Kombucha order', 'Thursday route. Paid by autopay.', 60)
) v
where not exists (select 1 from public.supply_reorders);
