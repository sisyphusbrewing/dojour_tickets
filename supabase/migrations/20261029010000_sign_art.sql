-- The taproom LED sign draws its own pictures (Sam, Oct 28 2026): customers
-- suggest something on /sign/ (a QR code at the bar), Claude draws it as 32x32
-- pixel art (edge function sign-art), a manager approves it on
-- /sign/review.html, and the sign shows approved art in turn. Beers on tap get
-- art too, approved automatically.
--
-- Art is 32 rows of 32 characters: "." is off, 1-9 and A-F pick colors
-- palette[1..15] (hex strings like "E09000").

create table if not exists public.sign_art (
  id bigint generated always as identity primary key,
  kind text not null default 'suggestion' check (kind in ('suggestion', 'beer')),
  prompt text not null,
  from_name text,
  caption text not null default '',
  palette text[] not null default '{}',
  rows text[] not null default '{}',
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  note text,                 -- why Claude or a manager turned it down
  beer_key text unique,      -- beers: lowercased name, so each beer is drawn once
  created_at timestamptz not null default now(),
  decided_at timestamptz,
  last_shown timestamptz
);
create index if not exists sign_art_status_idx on public.sign_art (status, last_shown);

alter table public.sign_art enable row level security;
create policy "Managers manage sign art" on public.sign_art for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));

-- The sign asks for the next picture: approved art, least recently shown first.
create or replace function public.sign_next()
returns json
language plpgsql
security definer
set search_path = public
as $$
declare a public.sign_art;
begin
  select * into a from public.sign_art
  where status = 'approved'
  order by last_shown nulls first, id
  limit 1
  for update skip locked;
  if not found then
    return json_build_object('id', null);
  end if;
  update public.sign_art set last_shown = now() where id = a.id;
  return json_build_object('id', a.id, 'caption', a.caption, 'palette', a.palette, 'rows', a.rows, 'kind', a.kind);
end $$;

revoke all on function public.sign_next() from public;
grant execute on function public.sign_next() to anon, authenticated;
