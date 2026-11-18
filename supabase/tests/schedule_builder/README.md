# Checking "builds the schedule"

`supabase/migrations/20261118060000_schedule_builder.sql` lets a staff login
be marked "builds the schedule" (Sam, Nov 18 2026: one of the bartenders
"wants to take over making the schedule"). On the Schedule that login does
what a manager does, and everywhere else it stays the staff login it is.
This runs those rules on a throwaway Postgres on your own machine, never on
the real database. It needs the schedule, the staffing numbers and the usual
week loaded first, because the new file changes functions from all three.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -f supabase/tests/staffing_needs/stub.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261117200000_staffing_needs.sql
    psql -d t -f supabase/migrations/20261117230000_early_show_start.sql
    psql -d t -f supabase/migrations/20261117290000_usual_week.sql
    psql -d t -f supabase/migrations/20261118060000_schedule_builder.sql
    psql -d t -A -t -f supabase/tests/schedule_builder/scenario.sql

`scenario.sql` checks: a staff login can't build before it has the mark and
can't give itself the mark; with the mark it drafts, posts, changes and
removes shifts, and the right people are told; it sees and answers a
coworker's time off but not its own (a manager answers that one, and it can
still take its own request back); it sees the days people can't work; it gets
the staffing numbers and sets one day by hand, but can't change the numbers
behind them; it saves, lists and fills from the usual week; it sets names and
who is on the schedule; the time clock's notices to managers don't reach it;
a plain staff login is still refused all of it; the mark does nothing for a
door login; taking the mark off puts things back; managers and the owner work
as before.

Each check prints `ok` or `FAIL`. Every line should say `ok` (34 of them).
Eight steps are meant to be refused (a staff login adding a shift and posting
before the mark, the builder approving their own time off and changing the
staffing numbers, and a plain staff login four times); the line above each
says so. An `ERROR` anywhere else is a real problem.

The older checks (`staff_schedule`, `staffing_needs`, `usual_week`) should
give the same results with this file loaded after theirs as without it.
