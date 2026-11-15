# Checking the staff schedule database rules

`supabase/migrations/20261115040000_staff_schedule.sql` holds the rules for
the staff schedule: who can see drafts, who can take a shift, who gets told.
These two files run those rules on a throwaway Postgres on your own machine,
never on the real database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql        # a bare stand-in for Supabase's logins and roles
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -A -t -f supabase/tests/staff_schedule/scenario.sql

`scenario.sql` walks one week: a manager drafts and posts shifts, one person
offers a shift up and another takes it, a time off request is asked, approved
and taken back. Nine lines of it are meant to fail (a staff login adding a
shift, taking a shift nobody offered, approving their own time off, and so
on); each prints an ERROR. Anything else printing ERROR is a real problem.
The last block prints every notice that was written, to read through.
