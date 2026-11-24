# Checking days we're closed

`supabase/migrations/20261124190000_closed_days.sql` lets a day be marked
closed on the Schedule (Sam, Nov 24 2026: "Can you mark on employee schedule
we will be closed Christmas Day and New Year's Day?"). This runs those rules
on a throwaway Postgres on your own machine, never on the real database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -f supabase/tests/staffing_needs/stub.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261117200000_staffing_needs.sql
    psql -d t -f supabase/migrations/20261117230000_early_show_start.sql
    psql -d t -f supabase/migrations/20261117290000_usual_week.sql
    psql -d t -f supabase/migrations/20261118060000_schedule_builder.sql
    psql -d t -f supabase/migrations/20261123230000_schedule_calendar.sql
    psql -d t -f supabase/migrations/20261124190000_closed_days.sql
    psql -d t -A -t -f supabase/tests/closed_days/scenario.sql

`scenario.sql` checks: Thanksgiving, Christmas Day and New Year's Day come
closed with the file; a plain staff login sees a closed day and its note but
no numbers, and can't close a day; the schedule builder closes one (the
number becomes nobody; no note reads "Closed"); no shift can be added to a
closed day or moved onto one, while a shift on an open day still changes; a
day with a shift on it can't be closed; "back to the usual" opens a day again;
0 people by hand alone is not closed; the phone calendar gets the closed days
(all day) beside the person's shifts.

Every check line should say `ok` (15 of them). Four steps are meant to be
refused; the line above each says so.

The older suites (staff_schedule, schedule_builder, schedule_calendar,
usual_week) put test shifts on days counted from today. Run them as their own
READMEs say, without this file: it closes real dates (Nov 26 2026, Dec 25
2026, Jan 1 2027) that can fall on their test days.
