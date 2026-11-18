# Checking the events@ inbox table

`supabase/migrations/20261118020000_events_inbox.sql` makes `events_threads`,
the sorted events@ inbox. These are customers' names and addresses, so the
check is about who can see and change them: nobody signed out, no regular
staff login, managers read (except lease and press emails, which are the owner's) and the owner reads and set the call (done / later) and
nothing else, and the hourly job refreshing a row keeps that call. This runs
on a throwaway Postgres, never on the real database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -c 'create function public.is_owner() returns boolean language sql stable security definer set search_path = public as $f$ select public.role_rank(public.my_role()) >= 4 and auth.uid() is not null $f$'
    psql -d t -c 'create function public.set_updated_at() returns trigger language plpgsql as $f$ begin new.updated_at = now(); return new; end $f$'
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated, service_role"
    psql -d t -f supabase/migrations/20261118020000_events_inbox.sql
    psql -d t -f supabase/migrations/20261118030000_events_owner_only.sql
    psql -d t -A -t -f supabase/tests/events_inbox/scenario.sql

Every check line should say `ok`. The steps that are meant to be refused say
how many `ERROR`s to expect just above them.
