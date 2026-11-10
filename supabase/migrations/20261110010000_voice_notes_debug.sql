-- Voice notes: a short log of what the phone did during each recording
-- (Nov 9 2026). A 15-minute recording came out empty with no clue why, so the
-- /voice/ page now saves its events here (which format, each piece's size,
-- mic paused or ended, page hidden). Only the recorder can see it, same as
-- the rest of the note.
alter table public.voice_notes add column if not exists debug jsonb;
