-- A comic's own CSS reveal (the Good-Enough-o-Matic): each comic_scores row
-- gets a private share_token, and css_reveal(token) returns that one comic's
-- score to anyone holding the link, without opening the managers-only table.
-- The total and grade match the CSS page (css/index.html): measured points +
-- house stars (5 a star, 12.5 until set), local pull 10 for Twin Cities
-- comics, and grades on a bell curve against every comic who has played
-- here (C within half a standard deviation of the mean, B/D the next band,
-- A +1.5, S +2, F below -1.5), moved one grade by the face. The stars, the face and the notes
-- themselves stay private. "room" says how much of each measured part is
-- still open (0 = maxed out, 1 = nothing yet), for improvement tips.

alter table public.comic_scores
  add column if not exists share_token text not null default replace(gen_random_uuid()::text, '-', '');

create unique index if not exists comic_scores_share_token on public.comic_scores (share_token);

create or replace function public.css_reveal(token text)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  with t as (
    select s.*,
      round(coalesce((s.points->>'draw_here')::numeric, 0) + coalesce((s.points->>'instagram')::numeric, 0)
      + coalesce((s.points->>'reddit')::numeric, 0) + coalesce((s.points->>'tiktok')::numeric, 0)
      + coalesce((s.points->>'youtube')::numeric, 0) + coalesce((s.points->>'momentum')::numeric, 0)
      + case when s.twin_cities then 10 else 0 end
      + case when s.house_stars is null then 12.5 else 5 * s.house_stars end) as total
    from public.comic_scores s
    where s.status = 'scored'
  ), curve as (
    select avg(total) as mu, greatest(stddev_pop(total), 1) as sd from t where not coalesce(draw_estimated, true)
  ), g as (
    select t.*, case
      when z >= 2 then 0 when z >= 1.5 then 1 when z >= 0.5 then 2
      when z >= -0.5 then 3 when z >= -1.5 then 4 else 5 end as tier
    from t, curve, lateral (select (t.total - curve.mu) / curve.sd as z) zz
    where t.share_token = token
  )
  select jsonb_build_object(
    'comedian', comedian,
    'score', total::int,
    'grade', substr('SABCDF', greatest(0, least(5, tier - likeability)) + 1, 1),
    'points', jsonb_build_object(
      'draw_here', points->'draw_here', 'instagram', points->'instagram', 'reddit', points->'reddit',
      'tiktok', points->'tiktok', 'youtube', points->'youtube', 'momentum', points->'momentum',
      'local', case when twin_cities then 10 else 0 end),
    'room', jsonb_build_object(
      'draw_here', round(1 - coalesce((points->>'draw_here')::numeric, 0) / 30, 2),
      'instagram', round(1 - coalesce((points->>'instagram')::numeric, 0) / 12, 2),
      'reddit', round(1 - coalesce((points->>'reddit')::numeric, 0) / 6, 2),
      'tiktok', round(1 - coalesce((points->>'tiktok')::numeric, 0) / 6, 2),
      'youtube', round(1 - coalesce((points->>'youtube')::numeric, 0) / 6, 2),
      'momentum', round(1 - coalesce((points->>'momentum')::numeric, 0) / 5, 2)),
    'per_show', per_show,
    'played_here', not coalesce(draw_estimated, true),
    'followers', jsonb_build_object('instagram', inputs->'ig', 'tiktok', inputs->'tiktok',
      'youtube', inputs->'youtube', 'reddit_votes', inputs->'reddit_votes'))
  from g
$$;

revoke all on function public.css_reveal(text) from public;
grant execute on function public.css_reveal(text) to anon, authenticated;
