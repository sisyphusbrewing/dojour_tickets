# Checking the cash drawer counts

`supabase/migrations/20261124220000_cash_drawer.sql` holds the rules for
counting the drawer on the Clock page: the first person in counts it, the last
person out counts it again, and managers see each day's counts next to what
GoTab says came in as cash. This runs them on a throwaway Postgres, never on
the real database. It builds on the time clock's test setup.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261117060000_time_clock.sql
    psql -d t -f supabase/migrations/20261124220000_cash_drawer.sql
    psql -d t -A -t -f supabase/tests/cash_drawer/scenario.sql

Every check prints `ok`. Steps meant to be refused say how many `ERROR`s to
expect on the line above them (11 in all); an `ERROR` anywhere else is a real
problem.
