# Checking the open mic on the Stream Deck

`supabase/migrations/20261118020000_mic_deck_lineup.sql` holds `mic_deck()`, the
one call the Stream Deck makes to run the Tuesday open mic lineup: START SHOW
loads it, START NEXT COMIC moves it on and starts the comic's clock, a tap on
UP NEXT skips a comic who isn't there. This runs it on a throwaway Postgres,
never on the real database.

    createdb t
    psql -d t -f supabase/tests/mic_host_picks/stub.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    for f in 20261016220000_stage_timer 20261110003000_mic_signups 20261116191500_mic_signup_cutoff_630 \
             20261117240000_mic_host_picks 20261117250000_mic_first_timers 20261117260000_mic_twelve_total \
             20261117270000_mic_women_spots 20261117280000_mic_women_thirty 20261118020000_mic_deck_lineup; do
      psql -d t -f supabase/migrations/$f.sql
    done
    psql -d t -A -t -f supabase/tests/mic_deck/scenario.sql

The stage timer file prints one ERROR about `supabase_realtime` (that only
exists on Supabase); ignore it. Every check line should say `ok`. Two steps at
the end are meant to be refused and print `ERROR`. Run it on a fresh database
each time.
