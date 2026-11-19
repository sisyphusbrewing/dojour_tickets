# Checking "Your night"

`supabase/migrations/20261119030000_guest_night.sql` holds the rules for the
guest's page (`night/`) and the bar's first-round list (`firstround/`): what a
guest with no link sees, how "find my tickets" matches an order, one first
beer per ticket, and that only staff see the bar's list. This runs them on a
throwaway Postgres, never on the real database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/tests/guest_night/stub.sql
    psql -d t -f supabase/migrations/20261119030000_guest_night.sql
    psql -d t -A -t -f supabase/tests/guest_night/scenario.sql

Every check line should say `ok`. The steps that are meant to be refused say
how many `ERROR`s to expect just above them.
