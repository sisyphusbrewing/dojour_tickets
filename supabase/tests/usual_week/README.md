# Checking the usual week

`supabase/migrations/20261117290000_usual_week.sql` keeps "the usual week":
the shifts a normal week has and who usually works each one (Sam, Nov 17 2026:
"...see what our schedules were like before and we can use that as the
template going forward"). A manager fills a week with it as drafts, or saves a
week as the new usual week. This runs those rules on a throwaway Postgres on
your own machine, never on the real database. It reuses the schedule's
stand-in for Supabase's logins and the staffing numbers' tables (a day set by
hand to nobody is a day the usual week leaves alone).

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -f supabase/tests/staffing_needs/stub.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261117200000_staffing_needs.sql
    psql -d t -f supabase/migrations/20261117230000_early_show_start.sql
    psql -d t -f supabase/migrations/20261117290000_usual_week.sql
    psql -d t -A -t -f supabase/tests/usual_week/scenario.sql

`scenario.sql` has a manager build a week by hand and save it as the usual
week, then fills later weeks from it and checks: the right shifts on the right
days, all drafts, with the same people; a second tap adds nothing; nobody is
told about drafts; a shift is left open when its person has approved time off,
never works that day of the week, or is off the schedule (and time off that is
only asked for leaves them on); a day that already has a shift and a day set
by hand to nobody are left alone; days already gone are skipped and a week
that is over is refused; saving a new usual week keeps the old one, marked as
replaced; and what staff, the door login and the owner may do. The weeks are
worked out from today, so it passes whenever it is run.

Each check prints `ok` or `FAIL`. Every line should say `ok` (23 of them).
Nine steps are meant to be refused (nothing saved yet, an empty week, a week
that is over, a staff login three times and at the table twice, the door
login); the line above each says how many `ERROR`s to expect. An `ERROR`
anywhere else is a real problem.
