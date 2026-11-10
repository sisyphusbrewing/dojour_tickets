# Tuesday open mic sign-up

Free stand-up open mic every Tuesday at 7 PM in the main taproom, from
Nov 17 2026. A few spots are booked ahead; the rest are drawn at random from
the online sign-ups (Sam, Nov 9 2026).

- `index.html` is the public sign-up form. It is embedded on
  sisyphusbrewing.com/pages/open-mic (iframe, sends its height with
  `micHeight`) and works on its own at staff.sisyphusbrewing.com/mic/.
  It calls `mic_signup()`, which puts the comic in for the next Tuesday.
  Sign-ups for a Tuesday close at 5 PM Central that day, then roll to the
  next week. One per email per week.
- `host.html` (staff login) is the host screen: pick the Tuesday, add the
  comics booked ahead, set how many open spots, tap Draw names. Booked comics
  go first, drawn ones after; Undo puts everyone back in the hat. Copy lineup
  puts the running order on the clipboard.
- Data: `public.mic_signups`, migration
  `supabase/migrations/20261110003000_mic_signups.sql`.

No emails go out yet; comics find out at the mic.
