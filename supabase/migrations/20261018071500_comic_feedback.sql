-- Comics pitch feedback: Sam texts the tap-through (comics/index.html,
-- sisyphusbrewing.com/pages/comics?c=<name>) to a few comics, and the last
-- screen asks them to roast it. Answers go through comic_feedback_submit();
-- comic_view() logs how far each named link got, so Sam can see who opened it.
-- Staff (signed in) and the service key read both tables.

create table if not exists public.comic_feedback (
  id           uuid primary key default gen_random_uuid(),
  tag          text,                                -- ?c= from the link Sam sent
  name         text,
  data         jsonb not null default '{}'::jsonb,  -- the answers
  max_screen   int,
  notified_at  timestamptz,                         -- when booking@ was emailed
  created_at   timestamptz not null default now()
);

create table if not exists public.comic_views (
  tag          text primary key,
  opens        int not null default 1,
  max_screen   int not null default 1,
  first_seen   timestamptz not null default now(),
  last_seen    timestamptz not null default now()
);

alter table public.comic_feedback enable row level security;
alter table public.comic_views enable row level security;

create policy "Allow authenticated staff full access to comic_feedback"
  on public.comic_feedback for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to comic_feedback"
  on public.comic_feedback for all to service_role using (true) with check (true);
create policy "Allow authenticated staff full access to comic_views"
  on public.comic_views for all to authenticated using (true) with check (true);
create policy "Allow service_role full access to comic_views"
  on public.comic_views for all to service_role using (true) with check (true);

create or replace function public.comic_feedback_submit(p_tag text, p_data jsonb, p_max_screen int default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare new_id uuid;
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if length(p_data::text) > 12000 then
    raise exception 'That is a lot of notes. Save some for the act-out.';
  end if;
  if (select count(*) from public.comic_feedback where created_at > now() - interval '1 hour') >= 30 then
    raise exception 'Lots of notes right now. Try again in a bit.';
  end if;
  insert into public.comic_feedback (tag, name, data, max_screen)
    values (nullif(left(trim(p_tag), 80), ''), nullif(left(trim(p_data->>'name'), 120), ''), p_data, p_max_screen)
    returning id into new_id;
  return new_id;
end $$;

create or replace function public.comic_view(p_tag text, p_screen int)
returns void language plpgsql security definer set search_path = public as $$
declare t text := nullif(left(trim(p_tag), 80), '');
begin
  if t is null then return; end if;
  insert into public.comic_views (tag, max_screen) values (t, greatest(1, least(coalesce(p_screen, 1), 20)))
  on conflict (tag) do update set
    max_screen = greatest(comic_views.max_screen, least(coalesce(p_screen, 1), 20)),
    opens = comic_views.opens + case when p_screen = 1 then 1 else 0 end,
    last_seen = now();
end $$;

revoke all on function public.comic_feedback_submit(text, jsonb, int) from public;
revoke all on function public.comic_view(text, int) from public;
grant execute on function public.comic_feedback_submit(text, jsonb, int) to anon, authenticated, service_role;
grant execute on function public.comic_view(text, int) to anon, authenticated, service_role;
