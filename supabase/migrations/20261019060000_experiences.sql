-- Ticket experiences: things in the club every guest gets to do once (the
-- photo booth first). A guest scans their ticket (or types the ticket email)
-- at the experience; each ticket on tonight's order is worth one use of each
-- experience, so a party of four gets four.
--
-- Experience screens are not staff logins. Each machine holds a device key
-- (?key=... once, then remembered on that machine) and calls exp_scan and
-- exp_redeem as anon. Only the key's hash is stored.

create table if not exists public.experiences (
  slug       text primary key,
  name       text not null,
  active     boolean not null default true,
  created_at timestamptz not null default now()
);
insert into public.experiences (slug, name) values ('booth', 'Photo booth') on conflict do nothing;

create table if not exists public.experience_devices (
  key_hash   text primary key,
  label      text not null,
  created_at timestamptz not null default now()
);

-- One row per scan. A scan holds one use for 10 minutes; exp_redeem settles
-- it with the real count (a booth strip per person, say).
create table if not exists public.experience_uses (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  experience  text not null references public.experiences (slug),
  email       text not null,
  show_date   text,
  show_title  text,
  redeemed_at timestamptz,
  uses        int not null default 0
);
create index if not exists experience_uses_lookup on public.experience_uses (experience, lower(email), show_date);

alter table public.experiences enable row level security;
alter table public.experience_devices enable row level security;
alter table public.experience_uses enable row level security;
create policy "Staff read experiences" on public.experiences for select to authenticated using (true);
create policy "Staff read experience uses" on public.experience_uses for select to authenticated using (true);
create policy "Managers only" on public.experiences as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
create policy "Managers only" on public.experience_devices as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
create policy "Managers only" on public.experience_uses as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));

create or replace function public.exp_key_ok(p_key text)
returns boolean language sql stable security definer set search_path = public, extensions as $$
  select exists (select 1 from public.experience_devices
                 where key_hash = encode(extensions.digest(coalesce(p_key, ''), 'sha256'), 'hex'));
$$;

-- Tonight's order behind a scan: the ticket email, or a QR whose text holds
-- the ticket's id (our unique_id, or the Dojour/Shopify id inside it).
-- Returns the email + show the order belongs to; with two shows tonight the
-- later one wins.
create or replace function public.exp_find(p_code text)
returns table (email text, show_date text, show_title text, guest_name text)
language sql stable security definer set search_path = public as $$
  with code as (select trim(coalesce(p_code, '')) as c),
  tokens as (
    select tok from code, regexp_split_to_table(code.c, '[^A-Za-z0-9_-]+') tok where length(tok) >= 6
  ),
  hit as (
    select t.* from public.tickets t, code
     where public.door_is_tonight(t.show_date) and t.email <> ''
       and (lower(t.email) = lower(code.c)
            or t.unique_id = code.c
            or exists (select 1 from tokens
                        where t.unique_id = tokens.tok
                           or t.unique_id like 'dj\_%\_' || tokens.tok
                           or t.unique_id like 'shopify\_' || tokens.tok || '\_%'))
     order by t.show_date desc
     limit 1
  )
  select lower(hit.email), hit.show_date, hit.show_title, hit.guest_name from hit;
$$;

-- Uses left for this email at this show and experience. Unredeemed scans
-- hold one use for 10 minutes, then let go.
create or replace function public.exp_left(p_experience text, p_email text, p_show_date text, p_show_title text)
returns int language sql stable security definer set search_path = public as $$
  select coalesce((select sum(t.tickets)::int from public.tickets t
                   where lower(t.email) = lower(p_email)
                     and t.show_date = p_show_date and t.show_title = p_show_title), 0)
       - coalesce((select sum(case when u.redeemed_at is not null then u.uses else 1 end)::int
                   from public.experience_uses u
                   where u.experience = p_experience and lower(u.email) = lower(p_email)
                     and u.show_date = p_show_date and u.show_title = p_show_title
                     and (u.redeemed_at is not null or u.created_at > now() - interval '10 minutes')), 0);
$$;

-- A scan at an experience. Returns the show and a pass id, or a reason:
-- key (bad device key), closed, no_ticket, used. The code "test" always
-- unlocks, for setting up cameras and printers.
create or replace function public.exp_scan(p_key text, p_experience text, p_code text)
returns json language plpgsql security definer set search_path = public as $$
declare
  v_found record;
  v_left int;
  v_id uuid;
begin
  if not public.exp_key_ok(p_key) then
    return json_build_object('ok', false, 'reason', 'key');
  end if;
  if not exists (select 1 from public.experiences where slug = p_experience and active) then
    return json_build_object('ok', false, 'reason', 'closed');
  end if;
  if lower(trim(coalesce(p_code, ''))) = 'test' then
    insert into public.experience_uses (experience, email, show_title)
    values (p_experience, 'test', 'Test') returning id into v_id;
    return json_build_object('ok', true, 'pass', v_id, 'show_title', 'Booth Test',
      'show_date', to_char(now() at time zone 'America/Chicago', 'Dy, Mon FMDD'), 'name', 'Test', 'left', 4);
  end if;

  select * into v_found from public.exp_find(p_code);
  if v_found.email is null then
    return json_build_object('ok', false, 'reason', 'no_ticket');
  end if;
  v_left := public.exp_left(p_experience, v_found.email, v_found.show_date, v_found.show_title);
  if v_left < 1 then
    return json_build_object('ok', false, 'reason', 'used');
  end if;

  insert into public.experience_uses (experience, email, show_date, show_title)
  values (p_experience, v_found.email, v_found.show_date, v_found.show_title) returning id into v_id;
  return json_build_object('ok', true, 'pass', v_id,
    'show_title', v_found.show_title,
    'show_date', split_part(v_found.show_date, ' •', 1),
    'name', split_part(coalesce(v_found.guest_name, ''), ' ', 1),
    'left', v_left);
end;
$$;

-- Settle a pass: p_uses people used it (capped at what the order has left).
-- Returns the uses granted; 0 means the pass is unknown, stale or settled.
create or replace function public.exp_redeem(p_key text, p_pass uuid, p_uses int default 1)
returns int language plpgsql security definer set search_path = public as $$
declare
  u public.experience_uses;
  v_max int;
begin
  if not public.exp_key_ok(p_key) then return 0; end if;
  select * into u from public.experience_uses where id = p_pass for update;
  if u.id is null or u.redeemed_at is not null or u.created_at < now() - interval '30 minutes' then
    return 0;
  end if;
  if u.email = 'test' then
    v_max := 4;
  else
    -- The pass itself already holds one use inside exp_left.
    v_max := public.exp_left(u.experience, u.email, u.show_date, u.show_title) + 1;
  end if;
  update public.experience_uses
     set redeemed_at = now(), uses = least(greatest(coalesce(p_uses, 1), 1), greatest(v_max, 1))
   where id = p_pass
  returning uses into v_max;
  return v_max;
end;
$$;

revoke all on function public.exp_key_ok(text), public.exp_find(text), public.exp_left(text, text, text, text),
  public.exp_scan(text, text, text), public.exp_redeem(text, uuid, int) from public, anon, authenticated;
grant execute on function public.exp_scan(text, text, text), public.exp_redeem(text, uuid, int) to anon, authenticated;
