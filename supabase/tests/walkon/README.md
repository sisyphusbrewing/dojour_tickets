# Checking walk-on songs

`supabase/migrations/20261119230000_walkon_songs.sql` holds the walk-on song
rules: the comic's pick page, the Booking board link and what the office PC's
walk-on helper reads on show night. This runs them on a throwaway Postgres,
never on the real database.

    createdb t
    psql -d t -f supabase/tests/walkon/stub.sql
    psql -d t -f supabase/migrations/20261119230000_walkon_songs.sql
    psql -d t -A -t -f supabase/tests/walkon/scenario.sql 2>&1 | grep -v '^$'

Every line should say `ok` (some come out as NOTICE lines). Run it on a fresh
database each time.
