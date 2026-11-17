# Checking the "how many people a day needs" rules

`supabase/migrations/20261117200000_staffing_needs.sql` reads the website's
list of upcoming shows and works out how many people each day needs (Sam, Nov
17 2026: "The scheduler should read the calendar for upcoming events and then
say how many people we need to schedule because of it"). This runs those rules
on a throwaway Postgres on your own machine, never on the real database. It
reuses the schedule's stand-in for Supabase's logins, and `stub.sql` here adds
bare copies of the two tables the rules read (upcoming showtimes and tickets).

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -f supabase/tests/staffing_needs/stub.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261117200000_staffing_needs.sql
    psql -d t -f supabase/migrations/20261117230000_early_show_start.sql
    psql -d t -A -t -f supabase/tests/staffing_needs/scenario.sql

`scenario.sql` puts a few shows on the calendar (a two-show Friday with
General and Premium seats, the free Thursday showcase, a Thursday with both, a
Sunday show at closing time, a show on a closed Monday, a cancelled show, a
5 PM show, a free event at 6, a show at 6:30) and
checks each day's number and the reason given for it: a plain weekday, a long
day split into an opener and a closer, the extra person and when they start
(90 minutes before a show, an hour before one at 6 PM or earlier: Sam, Nov 17
2026; that rule is the second migration above),
tickets sold without the venue's own holds or comps, a full room, changed
numbers, one day set by hand and put back, and what staff and the door login
may see. The days are worked out from today, so it passes whenever it is run.

Each check prints `ok` or `FAIL`. Every line should say `ok`. Nine steps are
meant to be refused (a number out of range, twice, more than two months at once, a
staff login changing numbers or reading the tables, the door login); the line
above each says how many `ERROR`s to expect. An `ERROR` anywhere else is a
real problem.
