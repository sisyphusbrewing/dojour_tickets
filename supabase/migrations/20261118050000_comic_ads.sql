-- Ad results for the comics Sisyphus Comedy runs ads for (Sam, Nov 17 2026:
-- "We should create a simple platform on the staff page for Colin (and other
-- comics) to access these metrics", and "It should have them login").
--
-- The page is staff.sisyphusbrewing.com/results/. Each comic signs in with a
-- login and password of their own and sees only their own shows: what we
-- spent, how many people saw the ads, how many clicked, what a click cost,
-- per platform (Facebook/Instagram, Reddit), and the ticket counts we've
-- been told.
--
-- Comic logins are NOT staff logins. They live here, in their own table, and
-- never touch Supabase's sign-in (auth.users). A staff-site login with no
-- role counts as a door login, which could open tonight's guest list; a comic
-- must never get that. So a comic signs in through comic_ads_login(), which
-- hands back a session code that only comic_ads_report() understands.
--
-- Names, logins and numbers live only in the database, never in this public
-- repo. comic_ads_refresh.py (GitHub Actions) keeps the Reddit numbers (and
-- the Facebook/Instagram numbers once Meta gives it a token) up to date; a
-- daily Claude task fills in Facebook/Instagram from Adspirer until then.

create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;

-- One row per comic.
create table if not exists public.comic_ad_clients (
  id bigint generated always as identity primary key,
  login text not null unique check (login ~ '^[a-z0-9]{3,30}$'),
  name text not null,
  pass_hash text not null,
  active boolean not null default true,
  failed_logins int not null default 0,
  locked_until timestamptz,
  created_at timestamptz not null default now()
);

-- Sign-ins. Only a hash of the session code is kept.
create table if not exists public.comic_ad_sessions (
  token_hash text primary key,
  client_id bigint not null references public.comic_ad_clients(id),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '90 days'
);

-- One row per show we advertise (a run of nights can be one row).
create table if not exists public.comic_ad_shows (
  id bigint generated always as identity primary key,
  client_id bigint not null references public.comic_ad_clients(id),
  title text not null,            -- e.g. the venue and town
  show_date date not null,
  show_time text,                 -- e.g. "7 PM"
  budget numeric(10,2),           -- what the comic agreed to spend, all platforms
  ticket_link text,
  hidden boolean not null default false,
  created_at timestamptz not null default now()
);

-- One row per ad campaign. The totals are lifetime totals for the campaign,
-- written by the refresh job; they are replaced, never added to.
create table if not exists public.comic_ad_campaigns (
  id bigint generated always as identity primary key,
  show_id bigint not null references public.comic_ad_shows(id),
  platform text not null check (platform in ('meta', 'reddit')),
  account_id text not null,
  campaign_id text not null,
  starts_on date,
  ends_on date,
  spend numeric(10,2) not null default 0,
  impressions int not null default 0,
  reach int not null default 0,
  clicks int not null default 0,   -- link clicks (people who tapped through), not every tap on the ad
  data_through date,               -- the last day the platform's numbers cover
  refreshed_at timestamptz,
  unique (platform, campaign_id)
);

-- Ticket counts we've been told (by the comic, the venue or Punchup).
create table if not exists public.comic_ad_ticket_counts (
  id bigint generated always as identity primary key,
  show_id bigint not null references public.comic_ad_shows(id),
  counted_on date not null,
  sold int not null check (sold >= 0),
  note text,
  created_at timestamptz not null default now()
);

alter table public.comic_ad_clients enable row level security;
alter table public.comic_ad_sessions enable row level security;
alter table public.comic_ad_shows enable row level security;
alter table public.comic_ad_campaigns enable row level security;
alter table public.comic_ad_ticket_counts enable row level security;

-- Nobody reads these tables from a browser; only the functions below and the
-- service key (the refresh job, Claude) touch them.
revoke all on public.comic_ad_clients, public.comic_ad_sessions, public.comic_ad_shows,
  public.comic_ad_campaigns, public.comic_ad_ticket_counts from anon, authenticated;

-- Sign in. Gives back a session code, or says no. Ten wrong passwords in a
-- row lock that login for 15 minutes.
create or replace function public.comic_ads_login(p_login text, p_password text)
returns text language plpgsql security definer set search_path = public, extensions as $$
declare
  c public.comic_ad_clients;
  v_token text;
begin
  select * into c from public.comic_ad_clients
   where login = lower(trim(coalesce(p_login, ''))) and active;
  if c.id is null then
    raise exception 'Wrong login or password';
  end if;
  if c.locked_until is not null and c.locked_until > now() then
    raise exception 'Too many tries. Wait 15 minutes and try again.';
  end if;
  if c.pass_hash <> extensions.crypt(coalesce(p_password, ''), c.pass_hash) then
    update public.comic_ad_clients
       set failed_logins = failed_logins + 1,
           locked_until = case when failed_logins + 1 >= 10 then now() + interval '15 minutes' else null end
     where id = c.id;
    return null;
  end if;
  update public.comic_ad_clients set failed_logins = 0, locked_until = null where id = c.id;
  v_token := encode(extensions.gen_random_bytes(24), 'hex');
  insert into public.comic_ad_sessions (token_hash, client_id)
  values (encode(extensions.digest(v_token, 'sha256'), 'hex'), c.id);
  return v_token;
end;
$$;

-- Which comic a session code belongs to (null if it's unknown or expired).
create or replace function public.comic_ads_client(p_token text)
returns bigint language sql stable security definer set search_path = public, extensions as $$
  select s.client_id
    from public.comic_ad_sessions s
    join public.comic_ad_clients c on c.id = s.client_id and c.active
   where s.token_hash = encode(extensions.digest(coalesce(p_token, ''), 'sha256'), 'hex')
     and s.expires_at > now();
$$;

create or replace function public.comic_ads_logout(p_token text)
returns void language sql security definer set search_path = public, extensions as $$
  delete from public.comic_ad_sessions
   where token_hash = encode(extensions.digest(coalesce(p_token, ''), 'sha256'), 'hex');
$$;

-- Everything one comic's page shows, for that comic only.
create or replace function public.comic_ads_report(p_token text)
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  v_client bigint := public.comic_ads_client(p_token);
begin
  if v_client is null then
    raise exception 'Please sign in again';
  end if;
  return (
    select jsonb_build_object(
      'name', c.name,
      'shows', coalesce((
        select jsonb_agg(jsonb_build_object(
          'title', s.title,
          'show_date', s.show_date,
          'show_time', s.show_time,
          'budget', s.budget,
          'ticket_link', s.ticket_link,
          'platforms', coalesce((
            select jsonb_agg(jsonb_build_object(
              'platform', p.platform,
              'spend', p.spend,
              'impressions', p.impressions,
              'reach', p.reach,
              'clicks', p.clicks,
              'starts_on', p.starts_on,
              'ends_on', p.ends_on,
              'data_through', p.data_through,
              'refreshed_at', p.refreshed_at) order by p.platform)
            from (
              -- More than one campaign on a platform for a show adds up;
              -- reach is the most any one campaign reached (people can't be
              -- added across campaigns without counting someone twice).
              select platform, sum(spend) spend, sum(impressions) impressions, max(reach) reach,
                     sum(clicks) clicks, min(starts_on) starts_on, max(ends_on) ends_on,
                     min(data_through) data_through, max(refreshed_at) refreshed_at
                from public.comic_ad_campaigns where show_id = s.id group by platform
            ) p), '[]'::jsonb),
          'tickets', coalesce((
            select jsonb_agg(jsonb_build_object('counted_on', t.counted_on, 'sold', t.sold, 'note', t.note)
                             order by t.counted_on, t.id)
              from public.comic_ad_ticket_counts t where t.show_id = s.id), '[]'::jsonb)
        ) order by s.show_date >= current_date desc,
                   case when s.show_date >= current_date then s.show_date end asc,
                   s.show_date desc)
          from public.comic_ad_shows s
         where s.client_id = c.id and not s.hidden), '[]'::jsonb))
    from public.comic_ad_clients c where c.id = v_client);
end;
$$;

-- A comic can change their own password once signed in.
create or replace function public.comic_ads_set_password(p_token text, p_old text, p_new text)
returns void language plpgsql security definer set search_path = public, extensions as $$
declare
  v_client bigint := public.comic_ads_client(p_token);
begin
  if v_client is null then
    raise exception 'Please sign in again';
  end if;
  if length(coalesce(p_new, '')) < 8 then
    raise exception 'Make the new password at least 8 characters';
  end if;
  if not exists (select 1 from public.comic_ad_clients
                  where id = v_client and pass_hash = extensions.crypt(coalesce(p_old, ''), pass_hash)) then
    raise exception 'The current password is not right';
  end if;
  update public.comic_ad_clients set pass_hash = extensions.crypt(p_new, extensions.gen_salt('bf'))
   where id = v_client;
end;
$$;

revoke all on function public.comic_ads_login(text, text), public.comic_ads_client(text),
  public.comic_ads_logout(text), public.comic_ads_report(text),
  public.comic_ads_set_password(text, text, text) from public;
-- Supabase also grants new functions to anon and authenticated by name, so
-- the helper is taken back from them explicitly; only the four below are
-- for the page.
revoke all on function public.comic_ads_client(text) from anon, authenticated;
grant execute on function public.comic_ads_login(text, text), public.comic_ads_logout(text),
  public.comic_ads_report(text), public.comic_ads_set_password(text, text, text)
  to anon, authenticated;
