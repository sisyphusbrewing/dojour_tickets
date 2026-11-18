-- The events@ inbox, sorted (Sam, Nov 17 2026: "We should probably do this for
-- the events@ email as well", the day booking@ went onto the Booking board).
--
-- events@sisyphusbrewing.com is where the public writes: people who want to
-- rent the room or bring a group, customers with a ticket problem,
-- accessibility questions, donation requests, sales pitches. Nobody owns that
-- inbox, so things sit.
--
--   events_threads   one row per email conversation in events@, filed every
--                    hour by events_inbox.py (which only reads the mailbox),
--                    plus a manager's call on it (done, later).
--
-- Managers and the owner only: these are customers' names and addresses.
-- What is kept is the subject, who wrote and the first couple of lines;
-- never whole emails or attachments. Nothing here is ever deleted by a page:
-- a conversation that is dealt with is marked "done".

create table if not exists public.events_threads (
  key          text primary key,                     -- "gm:<Gmail thread id>"
  kind         text not null default 'other',        -- private | tickets | access | donation | comic | pitch | other
  subject      text,
  from_name    text,
  from_email   text,
  asked        text,                                 -- dates they mentioned, as written
  people       text,                                 -- how many people, as written ("25", "30-40")
  snippet      text,                                 -- the first lines of the latest message
  link         text,                                 -- opens the conversation in Gmail
  first_at     timestamptz,
  last_at      timestamptz,
  last_from    text,
  msg_count    int,
  waiting_on   text,                                 -- us | them
  status       text check (status in ('done', 'later')),   -- a manager's call; empty = new
  status_by    text,
  status_at    timestamptz,
  note         text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists events_threads_last_at_idx on public.events_threads (last_at desc);

create trigger events_threads_set_updated_at
  before update on public.events_threads
  for each row execute function public.set_updated_at();

alter table public.events_threads enable row level security;

-- Supabase hands every signed-in (and signed-out) visitor full rights on a new
-- table and leaves it to the policies to say no. Take those back: a manager
-- may read the rows and set the call on one, nothing else. Only the hourly
-- job (the service key) adds or rewrites rows.
revoke all on public.events_threads from anon, authenticated;
grant select on public.events_threads to authenticated;
grant update (status, status_by, status_at, note) on public.events_threads to authenticated;

create policy "Managers read" on public.events_threads for select to authenticated
  using ((select public.is_manager()));
create policy "Managers make the call" on public.events_threads for update to authenticated
  using ((select public.is_manager())) with check ((select public.is_manager()));
create policy "Allow service_role full access to events_threads"
  on public.events_threads for all to service_role using (true) with check (true);
