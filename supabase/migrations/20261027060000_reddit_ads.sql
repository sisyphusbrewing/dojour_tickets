-- Reddit Ads API connection, used only by the reddit-ads edge function
-- (service role). RLS on with no policies, so the browser can't read them.

create table if not exists public.reddit_auth (
  id int primary key default 1 check (id = 1),
  refresh_token text not null,
  scope text,
  updated_at timestamptz not null default now()
);

-- One-time "state" values for the Allow link, so only links we made can
-- connect an account.
create table if not exists public.reddit_oauth_state (
  state text primary key,
  created_at timestamptz not null default now(),
  used_at timestamptz
);

-- Hashed keys for calling the function (Claude's ad tooling).
create table if not exists public.reddit_tool_keys (
  key_hash text primary key,
  label text,
  created_at timestamptz not null default now()
);

alter table public.reddit_auth enable row level security;
alter table public.reddit_oauth_state enable row level security;
alter table public.reddit_tool_keys enable row level security;
