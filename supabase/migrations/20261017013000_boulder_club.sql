-- Boulder Club, the perks tab of the guest app (theme/templates/page.app.liquid).
-- A guest joins with just a first name and gets a private token kept on their
-- phone. Once a day they type the 4-digit code shown on the taproom TV to push
-- the boulder one step. Ten pushes and the next pint is free; the bartender
-- taps "Pour it" on the guest's phone, and the boulder rolls back to zero.
-- The TV code changes every 10 minutes, so it has to be read in the room.

create table if not exists public.club_members (
  id          bigint generated always as identity primary key,
  token       text unique not null default encode(extensions.gen_random_bytes(16), 'hex'),
  member_no   int unique not null,
  name        text not null,
  pushes      int not null default 0 check (pushes between 0 and 10),
  lifetime    int not null default 0,
  pints       int not null default 0,
  redeemed_at timestamptz,
  created_at  timestamptz not null default now()
);

create table if not exists public.club_pushes (
  member_id  bigint not null references public.club_members(id) on delete cascade,
  day        date not null,
  created_at timestamptz not null default now(),
  primary key (member_id, day)
);

-- Seed for the TV code. Never readable from the app.
create table if not exists public.club_secret (
  id     int primary key default 1 check (id = 1),
  secret text not null default encode(extensions.gen_random_bytes(32), 'hex')
);
insert into public.club_secret (id) values (1) on conflict do nothing;

alter table public.club_members enable row level security;
alter table public.club_pushes  enable row level security;
alter table public.club_secret  enable row level security;
create policy "Staff read club_members" on public.club_members for select to authenticated using (true);
create policy "Staff read club_pushes"  on public.club_pushes  for select to authenticated using (true);

-- 4-digit code for a 10-minute window.
create or replace function public.club_code_for(p_window bigint)
returns text language sql stable security definer set search_path = public, extensions as $$
  select lpad(((('x' || substr(encode(hmac(p_window::text, s.secret, 'sha256'), 'hex'), 1, 8))::bit(32)::bigint) % 10000)::text, 4, '0')
    from public.club_secret s where s.id = 1;
$$;

-- What the TV shows.
create or replace function public.club_tv_code()
returns json language sql stable security definer set search_path = public as $$
  select json_build_object(
    'code', public.club_code_for(floor(extract(epoch from now()) / 600)::bigint),
    'changes_at', to_timestamp((floor(extract(epoch from now()) / 600) + 1) * 600));
$$;

create or replace function public.club_state(p_token text)
returns json language sql stable security definer set search_path = public as $$
  select json_build_object(
    'member_no', m.member_no, 'name', m.name, 'pushes', m.pushes, 'lifetime', m.lifetime,
    'pints', m.pints, 'redeemed_at', m.redeemed_at, 'now', now(),
    'pushed_today', exists (select 1 from public.club_pushes p
                             where p.member_id = m.id and p.day = (now() at time zone 'America/Chicago')::date))
    from public.club_members m where m.token = p_token;
$$;

create or replace function public.club_join(p_name text)
returns json language plpgsql security definer set search_path = public as $$
declare n text := left(trim(coalesce(p_name, '')), 40); t text; no int;
begin
  if n = '' then raise exception 'Tell us what to call you'; end if;
  loop
    no := 1000 + floor(random() * 9000)::int;
    exit when not exists (select 1 from public.club_members where member_no = no);
  end loop;
  insert into public.club_members (name, member_no) values (n, no) returning token into t;
  return json_build_object('token', t, 'state', public.club_state(t));
end $$;

create or replace function public.club_push(p_token text, p_code text)
returns json language plpgsql security definer set search_path = public as $$
declare m public.club_members; w bigint := floor(extract(epoch from now()) / 600)::bigint;
        c text := regexp_replace(coalesce(p_code, ''), '\D', '', 'g');
begin
  select * into m from public.club_members where token = p_token;
  if m.id is null then raise exception 'We lost track of your card. Join again?'; end if;
  if c not in (public.club_code_for(w), public.club_code_for(w - 1)) then
    raise exception 'That is not the code on the TV right now';
  end if;
  if m.pushes >= 10 then raise exception 'You are at the top. Go get your pint.'; end if;
  insert into public.club_pushes (member_id, day)
       values (m.id, (now() at time zone 'America/Chicago')::date)
  on conflict do nothing;
  if not found then raise exception 'One push a day. The boulder will be here tomorrow.'; end if;
  update public.club_members set pushes = pushes + 1, lifetime = lifetime + 1 where id = m.id;
  return public.club_state(p_token);
end $$;

create or replace function public.club_redeem(p_token text)
returns json language plpgsql security definer set search_path = public as $$
begin
  update public.club_members set pushes = 0, pints = pints + 1, redeemed_at = now()
   where token = p_token and pushes >= 10;
  if not found then raise exception 'Not at the top yet'; end if;
  return public.club_state(p_token);
end $$;

revoke all on function public.club_code_for(bigint) from public, anon, authenticated;
revoke all on function public.club_tv_code() from public;
revoke all on function public.club_state(text) from public;
revoke all on function public.club_join(text) from public;
revoke all on function public.club_push(text, text) from public;
revoke all on function public.club_redeem(text) from public;
grant execute on function public.club_tv_code() to anon, authenticated, service_role;
grant execute on function public.club_state(text) to anon, authenticated, service_role;
grant execute on function public.club_join(text) to anon, authenticated, service_role;
grant execute on function public.club_push(text, text) to anon, authenticated, service_role;
grant execute on function public.club_redeem(text) to anon, authenticated, service_role;
