# Checking the reorder buttons

`supabase/migrations/20261117220000_supply_reorders.sql` holds the rules for
the Reorder buttons on the Supplies page: who can send an order, what the
email says, and the "already ordered in the last three days" stop. This runs
them on a throwaway Postgres, never on the real database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/tests/supply_reorders/stub.sql
    psql -d t -f supabase/migrations/20261117220000_supply_reorders.sql
    psql -d t -f supabase/migrations/20261117230000_supply_reorders_by_flavor.sql
    psql -d t -A -t -f supabase/tests/supply_reorders/scenario.sql

Every check line should say `ok`. The steps that are meant to be refused
(staff sending, writing orders straight into the table, the same order twice,
an all-zero order, editing a button's address) say how many `ERROR`s to
expect just above them.
