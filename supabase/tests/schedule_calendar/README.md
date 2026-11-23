# Checking "Put my shifts on my calendar"

`supabase/migrations/20261123230000_schedule_calendar.sql` gives each person
a private calendar link for their own posted shifts. This runs those rules on
a throwaway Postgres on your own machine, never on the real database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -f supabase/tests/staffing_needs/stub.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261117200000_staffing_needs.sql
    psql -d t -f supabase/migrations/20261123230000_schedule_calendar.sql
    psql -d t -A -t -f supabase/tests/schedule_calendar/scenario.sql

`scenario.sql` checks: nobody signed in, the door login and a login reading
the codes are refused; a staff login gets the same code each time; no login
can read the calendar itself, only the service key (the Edge Function); the
calendar holds the person's posted shifts only (no drafts, nothing older than
two months), in Minneapolis time, with the note and coworkers' first names;
"until close" ends at the day's closing time; a shift past midnight ends the
next morning; a shift handed to someone else leaves the calendar; a new link
stops the old one; an unknown code shows nothing; a login that is no longer
staff loses its calendar.

Every check line should say `ok` (9 of them). Four steps are meant to be
refused; the line above each says so.
