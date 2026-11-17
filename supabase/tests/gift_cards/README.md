# Checking the tap gift cards

`supabase/migrations/20261118000000_gift_cards.sql` holds the rules for the
gift cards: who can look, take money off, put money on, undo, switch off a
lost card, and that nothing is ever changed or deleted. This runs them on a
throwaway Postgres, never on the real database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261118000000_gift_cards.sql
    psql -d t -A -t -f supabase/tests/gift_cards/scenario.sql

Every check line should say `ok`. The steps that are meant to be refused say
how many `ERROR`s to expect just above them.
