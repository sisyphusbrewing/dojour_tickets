# Checking which drawing the sign shows next

`supabase/migrations/20261121043000_sign_next_sooner.sql` holds the rule
(it replaces `20261120230000_sign_next_fresh_first.sql`, which adds the
`shows` column, so run both).
This runs it on a throwaway Postgres, never on the real database.

    createdb t
    psql -d t -f supabase/tests/sign_next/stub.sql
    psql -d t -f supabase/migrations/20261120230000_sign_next_fresh_first.sql
    psql -d t -f supabase/migrations/20261121043000_sign_next_sooner.sql
    psql -d t -A -t -f supabase/tests/sign_next/scenario.sql 2>&1 | grep -v '^$'

Every line should say `ok`. Run it on a fresh database each time.
