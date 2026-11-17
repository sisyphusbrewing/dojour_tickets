# Checking the time clock database rules

`supabase/migrations/20261117060000_time_clock.sql` holds the rules for the
time clock (`/clock/`): who can clock in, what counts as "at the bar", who can
change hours, how a pay period adds up and what "payroll submitted" locks.
This runs those rules on a throwaway Postgres on your own machine, never on
the real database. It reuses the schedule's stand-in for Supabase's logins.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261117060000_time_clock.sql
    psql -d t -A -t -f supabase/tests/time_clock/scenario.sql

`scenario.sql` walks two pay periods with the stand-in logins (an owner, a manager, two staff, the door): tapping in and out
(with and without the bar sticker), undoing a tap, forgetting to clock out,
typing a time in by hand, a manager fixing hours, tips, writing in a shift
nobody clocked, the payroll totals, marking payroll submitted, tips typed
after payroll (they land in the next one), taking a submit back, and the
"did you forget to clock out?" nudge.

The `alter default privileges` line copies what Supabase does: it hands every
new table to the website's logins with full rights. The migration takes those
rights back, and the "cannot write hours straight into the table" check
proves it.

Each check prints `ok` or `FAIL` with what it was checking. Every line should
say `ok`. Some steps are meant to be refused (a staff login reading payroll,
changing hours that were already paid, and so on); the line above each says
how many `ERROR`s to expect. An `ERROR` anywhere else is a real problem.
The last block prints every notice that was written, to read through.

## The club wifi rule

`supabase/migrations/20261117210000_clock_wifi.sql` adds one rule: without the
tag at the bar, the big button only clocks someone in or out from the club's
wifi (Sam, Nov 17 2026: "they have to be connected to our wifi to do so").
`wifi.sql` checks it on a fresh throwaway database: the same steps as above,
then

    psql -d t -f supabase/migrations/20261117210000_clock_wifi.sql
    psql -d t -A -t -f supabase/tests/time_clock/wifi.sql

It walks: the rule is off until a manager sets the club wifi, a manager sets
it from the club, the button works on the wifi and is refused off it (with
nothing written), the tag works on any connection, writing a shift in by hand
still works from home, a made-up address doesn't get past the real one, a new
long (IPv6) address replaces the old one and covers every phone on that wifi,
and a manager switching the rule off. The addresses in it are made-up example
ones. Eight steps are meant to be refused; the rest print `ok`.

`scenario.sql` above should give the same answers with the wifi file loaded
as without it, because the rule is off until someone sets the club wifi.

