-- Why a recording needs a human (Sam, Nov 9 2026). The office PC writes a
-- note on the full-show row when it split the sets from the host's intros
-- instead of the stage timer, or when its camera check failed ("CAMERA: the
-- picture is nearly black 5 min in"). recording_mail.py sends CAMERA shows to
-- booking@ instead of the headliner.
alter table public.recordings add column if not exists note text;
