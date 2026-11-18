# Checking the Tuesday open mic host picks and draw

`supabase/migrations/20261117240000_mic_host_picks.sql` holds the rules for the
host's link (4 guaranteed comics), the 6:30 draw (8 spots since Nov 18 2026), and the running order.
This runs them on a throwaway Postgres, never on the real database.

    createdb t
    psql -d t -f supabase/tests/mic_host_picks/stub.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261110003000_mic_signups.sql
    psql -d t -f supabase/migrations/20261116191500_mic_signup_cutoff_630.sql
    psql -d t -f supabase/migrations/20261117240000_mic_host_picks.sql
    psql -d t -f supabase/migrations/20261117250000_mic_first_timers.sql
    psql -d t -f supabase/migrations/20261117260000_mic_twelve_total.sql
    psql -d t -f supabase/migrations/20261117270000_mic_women_spots.sql
    psql -d t -f supabase/migrations/20261117280000_mic_women_thirty.sql
    psql -d t -f supabase/migrations/20261118040000_mic_eight_spots.sql
    psql -d t -A -t -f supabase/tests/mic_host_picks/scenario.sql

Every check line should say `ok`. Six steps at the end are meant to be
refused and print `ERROR`. Run it on a fresh database each time.
