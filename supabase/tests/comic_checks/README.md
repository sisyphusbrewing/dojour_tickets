# Checking the printed comic checks

`supabase/migrations/20261119060000_comic_checks.sql` holds the rules for
printed checks: only the owner approves, the office PC only ever sees
approved checks, numbers are never reused, nothing is changed or deleted.
This runs them on a throwaway Postgres, never on the real database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/tests/comic_checks/stub.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated, service_role"
    psql -d t -f supabase/migrations/20261119060000_comic_checks.sql
    psql -d t -A -t -f supabase/tests/comic_checks/scenario.sql

Every check line should say `ok`. The steps that are meant to be refused say
how many `ERROR`s to expect just above them.
