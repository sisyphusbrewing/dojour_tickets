-- Read-only login for the nightly database backup on the office PC (Sam,
-- Nov 18 2026, on a decision card: "Yes, read-only backup login").
--
-- It can read every table in public, past and future, and change nothing.
-- It skips row-level security (bypassrls) because a backup has to see every
-- row; the rules that keep staff out of owner-only tables still hold for
-- every staff login. pg_dump uses it through the Supabase pooler.
--
-- Its password was made on the office PC and never left it: the role was
-- created with a SCRAM verifier the PC computed, which can't be used to log
-- in. So this file has no password; it is the record of what was granted.
-- To switch it off: alter role backup_reader nologin;

-- create role backup_reader login bypassrls password '<SCRAM verifier from the PC>';
grant usage on schema public to backup_reader;
grant select on all tables in schema public to backup_reader;
grant select on all sequences in schema public to backup_reader;
alter default privileges for role postgres in schema public grant select on tables to backup_reader;
alter default privileges for role postgres in schema public grant select on sequences to backup_reader;
