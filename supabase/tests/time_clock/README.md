# Checking the time clock database rules

`supabase/migrations/20261117060000_time_clock.sql` holds the rules for the
time clock (`/clock/`): who can clock in, what counts as "at the bar", who can
change hours, how a pay period adds up and what "payroll submitted" locks.
This runs those rules on a throwaway Postgres on your own machine, never on
the real database. It reuses the schedule's stand-in for Supabase's logins.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -f supabase/migrations/20261117060000_time_clock.sql
    psql -d t -A -t -f supabase/tests/time_clock/scenario.sql

`scenario.sql` walks two pay periods with the stand-in logins (an owner, a manager, two staff, the door): tapping in and out
(with and without the bar sticker), undoing a tap, forgetting to clock out,
typing a time in by hand, a manager fixing hours, tips, writing in a shift
nobody clocked, the payroll totals, marking payroll submitted, tips typed
after payroll (they land in the next one), taking a submit back, and the
"did you forget to clock out?" nudge.

Each check prints `ok` or `FAIL` with what it was checking. Every line should
say `ok`. Some steps are meant to be refused (a staff login reading payroll,
changing hours that were already paid, and so on); the line above each says
how many `ERROR`s to expect. An `ERROR` anywhere else is a real problem.
The last block prints every notice that was written, to read through.
