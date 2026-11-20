# Checking that self-made logins get nothing

`supabase/migrations/20261120090000_close_open_signups.sql` (Nov 20 2026
security audit) stops a login that has no row in `staff_roles` from counting
as a door login. This runs parts 1 to 3 of it on a throwaway Postgres, never
on the real database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/tests/open_signups/stub.sql
    sed '/^-- 4\./,$d' supabase/migrations/20261120090000_close_open_signups.sql | psql -d t
    psql -d t -A -t -f supabase/tests/open_signups/scenario.sql

Every check line should say `ok`; one `ERROR` is expected where it says so.
