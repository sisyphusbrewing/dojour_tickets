# Checking the kitchen display

`supabase/migrations/20261123030000_home_kitchen.sql` adds the kitchen
display's settings and list to the Our house board. This runs its rules on a
throwaway Postgres, never on the real database.

    createdb t
    psql -d t -f supabase/tests/home_projects/stub.sql
    psql -d t -f supabase/migrations/20261122230000_home_projects.sql
    psql -d t -f supabase/migrations/20261123030000_home_kitchen.sql
    psql -d t -A -t -f supabase/tests/home_kitchen/scenario.sql 2>&1 | grep -v '^$'

Every line should say `ok` (some come out as NOTICE lines).
