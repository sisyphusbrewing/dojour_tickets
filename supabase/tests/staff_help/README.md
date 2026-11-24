# Checking Help (the staff helper and "Tell Sam")

`supabase/migrations/20261124060000_staff_help.sql` keeps the staff handbook,
the questions staff ask the helper, and the notes staff send Sam. This runs
its rules on a throwaway Postgres on your own machine, never on the real
database.

    createdb t
    psql -d t -f supabase/tests/staff_schedule/stub.sql
    psql -d t -f supabase/migrations/20261115040000_staff_schedule.sql
    psql -d t -c "alter default privileges in schema public grant all on tables to anon, authenticated"
    psql -d t -f supabase/migrations/20261124060000_staff_help.sql
    psql -d t -A -t -f supabase/tests/staff_help/scenario.sql

`scenario.sql` checks: no login can read the handbook, the questions or the
notes directly; the shared door login can't send a note or see what the
helper knows; staff see only staff section titles, managers also manager
ones, never the owner's; only ideas and "just so you know" go without a
name; a note only links to the sender's own question; staff and managers see
only their own notes; only the owner sees Sam's list and the questions; the
email job hands each new note out once and logins can't run it; Sam's answer
reaches the sender's notices once (a note without a name tells nobody), and
the sender sees it on the page.

Every check line should say `ok` (14 of them). Eleven steps are meant to be
refused; the line above each says so.
