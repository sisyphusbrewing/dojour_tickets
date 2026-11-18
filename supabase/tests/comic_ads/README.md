# Checking the comic ad results page

`supabase/migrations/20261118050000_comic_ads.sql` holds the rules for
staff.sisyphusbrewing.com/ads/: each comic signs in with their own login and
sees only their own shows. This runs them on a throwaway Postgres, never on
the real database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261118050000_comic_ads.sql
    psql -d t -A -t -f supabase/tests/comic_ads/scenario.sql

Every check line should say `ok`. The steps that are meant to be refused say
how many `ERROR`s to expect just above them.
