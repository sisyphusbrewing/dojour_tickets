# Checking the events@ calendar on the Schedule

`supabase/migrations/20261124200000_venue_calendar.sql` puts the events@
Google Calendar's own events (private parties, rentals) on the staff Schedule
(Sam, Nov 24 2026: "can we pull those events from the calendar?"). This runs
those rules on a throwaway Postgres on your own machine, never on the real
database: the same steps as `supabase/tests/closed_days/README.md`, then

    psql -d t -f supabase/migrations/20261124200000_venue_calendar.sql
    psql -d t -A -t -f supabase/tests/venue_calendar/scenario.sql

`scenario.sql` checks: title words leave out short and common words; the
service key saves the calendar; staff see a private party with its time and
an all-day rental with none, and the calendar's copy of a website show isn't
listed twice; staff can't read the table or save to it; a timed private event
adds a person to the day, an all-day one doesn't; an event that leaves the
calendar is marked gone (not deleted) and leaves the Schedule; an empty read
never wipes the calendar; a shift on the phone calendar says what else is on.

Every check line should say `ok` (9 of them). Three steps are meant to be
refused; the line above each says so. `test_venue_calendar.py` checks the
reading of the calendar itself (repeats, moved weeks, all-day spans, holds).
