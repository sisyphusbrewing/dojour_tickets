-- Help: the staff help assistant, and "Tell Sam" (Sam, Nov 24 2026).
--
-- Sam wants staff to have an AI to ask questions and get tech support, with
-- far less reach than his own: it answers only from a staff handbook that
-- leaves out the lease, money, settlements, inboxes and people's private
-- details. Sam, same night: "One that allows Grace to submit things to me
-- more directly" and "one that allows staff to submit suggestions or
-- thoughts directly as well". So one page, /help/, does three things:
--
--   1. Ask: a question goes to the Edge Function `staff-help`, which reads
--      the handbook below and asks Claude. Claude gets no tools at all: it
--      can't send email, see money or look anything up. It only answers.
--   2. Tell Sam: an idea, something someone needs from Sam (Grace's
--      requests), something broken, or just so you know. Ideas and FYIs can
--      go without a name. Sam gets each one by email (schedule_notify.py,
--      which already watches every two minutes) and answers on the page; the
--      sender sees the answer and is told the usual way (schedule_outbox).
--   3. When the helper can't solve something, one tap sends the question and
--      what it said to Sam the same way.
--
-- Nobody reads these tables directly. The page and the Edge Function go
-- through the functions below; the handbook and the question log are read
-- only with the service key (the Edge Function) and by the owner login.

-- ---------- The handbook ----------
-- One row per section. min_role: the lowest login that may be told it
-- (staff, manager, owner). Written with the service key by whoever refreshes
-- the handbook; the text lives only here and in the project's private files,
-- not in this public repo.
create table if not exists public.help_handbook (
  slug text primary key,
  title text not null,
  min_role text not null default 'staff' check (min_role in ('staff', 'manager', 'owner')),
  sort int not null default 100,
  body text not null,
  updated_at timestamptz not null default now()
);
alter table public.help_handbook enable row level security;
revoke all on public.help_handbook from anon, authenticated;

-- ---------- What staff asked ----------
-- Written by the Edge Function (service key). Sam reads it to see what the
-- handbook is missing; it is also the helper's daily limit per person.
create table if not exists public.help_questions (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users (id) on delete set null,
  question text not null,
  answer text not null default '',
  needs_sam boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists help_questions_user_idx on public.help_questions (user_id, created_at desc);
alter table public.help_questions enable row level security;
revoke all on public.help_questions from anon, authenticated;

-- ---------- Notes to Sam ----------
create table if not exists public.help_notes (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users (id) on delete set null,   -- null = sent without a name
  kind text not null check (kind in ('idea', 'need', 'broken', 'fyi', 'help')),
  body text not null check (length(body) between 1 and 6000),
  need_by date,                                   -- "Something I need from Sam": by when, if it matters
  question_id bigint references public.help_questions (id) on delete set null,
  status text not null default 'new' check (status in ('new', 'seen', 'done')),
  answer text,
  answered_at timestamptz,
  alerted_at timestamptz,                         -- when Sam was emailed about it
  created_at timestamptz not null default now()
);
create index if not exists help_notes_user_idx on public.help_notes (user_id, created_at desc);
create index if not exists help_notes_unalerted_idx on public.help_notes (id) where alerted_at is null;
alter table public.help_notes enable row level security;
revoke all on public.help_notes from anon, authenticated;

-- The owner's login: role_rank 4.
create or replace function public.help_is_owner()
returns boolean language sql stable security definer set search_path = public as $$
  select auth.uid() is not null and public.role_rank(public.my_role()) >= 4;
$$;

-- What each kind is called, in emails and on the page.
create or replace function public.help_kind_label(p_kind text)
returns text language sql immutable set search_path = public as $$
  select case p_kind when 'idea' then 'Idea' when 'need' then 'Needs Sam' when 'broken' then 'Something''s broken'
                     when 'fyi' then 'Just so you know' when 'help' then 'The helper couldn''t solve it' else p_kind end;
$$;

-- Send Sam a note. Any staff, manager or owner login (not the shared door
-- login, which comics use). p_anonymous leaves the name off, for ideas and
-- FYIs only: a request or a problem needs someone to answer. Twenty a day per
-- login is plenty and stops a stuck button from flooding Sam.
create or replace function public.help_note_send(p_kind text, p_body text, p_need_by date default null,
                                                 p_anonymous boolean default false, p_question_id bigint default null)
returns bigint language plpgsql security definer set search_path = public as $$
declare v_id bigint; v_me uuid := auth.uid(); v_body text := btrim(coalesce(p_body, ''));
begin
  if v_me is null then raise exception 'Please sign in again.'; end if;
  if public.role_rank(public.my_role()) < 2 then raise exception 'Staff only.'; end if;
  if p_kind not in ('idea', 'need', 'broken', 'fyi', 'help') then raise exception 'Pick what kind of note this is.'; end if;
  if v_body = '' then raise exception 'Write something first.'; end if;
  if length(v_body) > 6000 then raise exception 'That is too long. Keep it under 6,000 letters.'; end if;
  if coalesce(p_anonymous, false) and p_kind not in ('idea', 'fyi') then
    raise exception 'Only ideas and "just so you know" notes can go without your name.';
  end if;
  if not coalesce(p_anonymous, false)
     and (select count(*) from public.help_notes where user_id = v_me and created_at > now() - interval '1 day') >= 20 then
    raise exception 'That is 20 notes today. Sam will get to them; try again tomorrow.';
  end if;
  -- Notes without a name can't be counted per person, so all of them together.
  if coalesce(p_anonymous, false)
     and (select count(*) from public.help_notes where user_id is null and created_at > now() - interval '1 day') >= 40 then
    raise exception 'Too many notes without a name today. Try again tomorrow, or send it with your name.';
  end if;
  -- A question only links up if it was this person's own.
  if p_question_id is not null and not exists (select 1 from public.help_questions where id = p_question_id and user_id = v_me) then
    p_question_id := null;
  end if;
  insert into public.help_notes (user_id, kind, body, need_by, question_id)
  values (case when coalesce(p_anonymous, false) then null else v_me end, p_kind, v_body,
          case when p_kind = 'need' then p_need_by end, p_question_id)
  returning id into v_id;
  return v_id;
end $$;

-- My own notes (named ones; a note sent without a name can't be traced back,
-- not even by its sender), newest first, with Sam's answer.
create or replace function public.help_my_notes()
returns table (id bigint, kind text, body text, need_by date, status text, answer text, answered_at timestamptz, created_at timestamptz)
language sql stable security definer set search_path = public as $$
  select n.id, n.kind, n.body, n.need_by, n.status, n.answer, n.answered_at, n.created_at
  from public.help_notes n
  where auth.uid() is not null and n.user_id = auth.uid() and n.created_at > now() - interval '120 days'
  order by n.created_at desc limit 50;
$$;

-- Sam's list: everything sent to him, open ones first.
create or replace function public.help_inbox()
returns table (id bigint, kind text, body text, need_by date, status text, answer text, answered_at timestamptz,
               created_at timestamptz, from_name text, question text, helper_answer text)
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.help_is_owner() then raise exception 'Owner only.'; end if;
  return query
  select n.id, n.kind, n.body, n.need_by, n.status, n.answer, n.answered_at, n.created_at,
         case when n.user_id is null then null else public.schedule_name(n.user_id) end,
         q.question, q.answer
  from public.help_notes n left join public.help_questions q on q.id = n.question_id
  where n.status <> 'done' or n.created_at > now() - interval '60 days'
  order by (n.status = 'done'), n.created_at desc limit 200;
end $$;

-- Sam marks a note seen or done, and can answer it. An answer reaches the
-- sender on the page and through their usual notices (email or text).
create or replace function public.help_note_answer(p_id bigint, p_answer text default null, p_status text default 'done')
returns void language plpgsql security definer set search_path = public as $$
declare n public.help_notes; v_answer text := nullif(btrim(coalesce(p_answer, '')), '');
begin
  if not public.help_is_owner() then raise exception 'Owner only.'; end if;
  if p_status not in ('new', 'seen', 'done') then raise exception 'Unknown status.'; end if;
  select * into n from public.help_notes where id = p_id;
  if not found then raise exception 'No such note.'; end if;
  update public.help_notes
     set status = p_status,
         answer = coalesce(v_answer, answer),
         answered_at = case when v_answer is not null then now() else answered_at end
   where id = p_id;
  if v_answer is not null and n.user_id is not null then
    perform public.schedule_tell(n.user_id, 'help_answer',
      'Sam answered your note ("' || left(regexp_replace(n.body, '\s+', ' ', 'g'), 60)
      || case when length(n.body) > 60 then '...' else '' end || '"): ' || v_answer);
  end if;
end $$;

-- The questions staff asked the helper lately, for Sam.
create or replace function public.help_recent_questions()
returns table (id bigint, question text, answer text, needs_sam boolean, created_at timestamptz, from_name text)
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.help_is_owner() then raise exception 'Owner only.'; end if;
  return query
  select q.id, q.question, q.answer, q.needs_sam, q.created_at,
         case when q.user_id is null then null else public.schedule_name(q.user_id) end
  from public.help_questions q order by q.created_at desc limit 100;
end $$;

-- What the helper knows about, for "What I can help with" on the page:
-- the titles of the sections this login may be told, never their text.
create or replace function public.help_contents()
returns table (title text)
language sql stable security definer set search_path = public as $$
  select h.title from public.help_handbook h
  where auth.uid() is not null and public.role_rank(public.my_role()) >= 2
    and public.role_rank(public.my_role()) >= public.role_rank(h.min_role)
  order by h.sort, h.title;
$$;

-- For schedule_notify.py (service key): new notes Sam hasn't been emailed
-- about, each handed out once.
create or replace function public.help_alerts()
returns table (id bigint, kind text, body text, need_by date, from_name text, question text, helper_answer text, created_at timestamptz)
language plpgsql security definer set search_path = public as $$
begin
  return query
  with sent as (
    update public.help_notes n set alerted_at = now()
     where n.alerted_at is null
    returning n.id, n.kind, n.body, n.need_by, n.user_id, n.question_id, n.created_at
  )
  select s.id, s.kind, s.body, s.need_by,
         case when s.user_id is null then null else public.schedule_name(s.user_id) end,
         q.question, q.answer, s.created_at
  from sent s left join public.help_questions q on q.id = s.question_id
  order by s.id;
end $$;

revoke all on function public.help_is_owner(), public.help_kind_label(text),
  public.help_note_send(text, text, date, boolean, bigint), public.help_my_notes(), public.help_inbox(),
  public.help_note_answer(bigint, text, text), public.help_recent_questions(), public.help_contents(),
  public.help_alerts() from public, anon;
grant execute on function public.help_note_send(text, text, date, boolean, bigint), public.help_my_notes(),
  public.help_inbox(), public.help_note_answer(bigint, text, text), public.help_recent_questions(),
  public.help_contents(), public.help_kind_label(text) to authenticated;
revoke all on function public.help_alerts() from authenticated;
grant execute on function public.help_alerts() to service_role;
