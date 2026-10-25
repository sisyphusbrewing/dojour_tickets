-- CSS, the Comic Scoring System (css/index.html, a tile on the staff hub).
-- One row per comic. css_score.py ("Comic scores" action) fills the measured
-- part: followers, Reddit buzz, tickets per show here, and the points they
-- earn (points jsonb, everything except the house score). Managers add the
-- rest on the page: house stars (1-5, 5 points each, 12.5 until set), the
-- likeability face (+1 moves the grade up one, -1 down one) and notes.
-- The page adds it up; tiers are calibrated to break-even (35 tickets/show):
-- D under 35 = don't book, C 35-44, B 45-59, A 60+.
-- status: 'requested' (typed into the page, waiting for the action),
-- 'scored', or 'not_found' (no accounts found for that name).
-- Managers only: same "authenticated + restrictive is_manager()" pair as the
-- other staff tables (20261018031000_manager_only.sql).

create table if not exists public.comic_scores (
  comedian      text primary key,
  status        text not null default 'requested' check (status in ('requested', 'scored', 'not_found')),
  points        jsonb,                 -- {"draw_here":..,"reddit":..,"instagram":..,"tiktok":..,"youtube":..,"local":..,"momentum":..}
  inputs        jsonb,                 -- followers, handles, Reddit votes, runs here
  per_show      integer,               -- tickets/show used for "draw here"
  draw_estimated boolean,              -- true when they never played here
  twin_cities   boolean not null default false,
  house_stars   smallint check (house_stars between 1 and 5),
  likeability   smallint not null default 0 check (likeability between -1 and 1),
  requested_by  text,
  scored_at     timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create trigger comic_scores_set_updated_at
  before update on public.comic_scores
  for each row execute function public.set_updated_at();

create table if not exists public.comic_notes (
  id          uuid primary key default gen_random_uuid(),
  comedian    text not null references public.comic_scores (comedian) on update cascade on delete cascade,
  body        text not null check (length(body) between 1 and 2000),
  author      text,                    -- login email
  created_at  timestamptz not null default now()
);

create index if not exists comic_notes_comedian on public.comic_notes (comedian, created_at);

alter table public.comic_scores enable row level security;
alter table public.comic_notes enable row level security;

create policy "Allow authenticated staff full access to comic_scores"
  on public.comic_scores for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to comic_scores"
  on public.comic_scores for all to service_role using (true) with check (true);
create policy "Managers only" on public.comic_scores as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));

create policy "Allow authenticated staff full access to comic_notes"
  on public.comic_notes for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to comic_notes"
  on public.comic_notes for all to service_role using (true) with check (true);
create policy "Managers only" on public.comic_notes as restrictive for all to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
