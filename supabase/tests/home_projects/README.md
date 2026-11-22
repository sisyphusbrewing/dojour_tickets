# Checking the Our house board

`supabase/migrations/20261122230000_home_projects.sql` holds the home board's
rules (the wall key reads, the phone key edits, nothing is ever deleted). This
runs them on a throwaway Postgres, never on the real database.

    createdb t
    psql -d t -f supabase/tests/home_projects/stub.sql
    psql -d t -f supabase/migrations/20261122230000_home_projects.sql
    psql -d t -A -t -f supabase/tests/home_projects/scenario.sql 2>&1 | grep -v '^$'

Every line should say `ok` (some come out as NOTICE lines).
