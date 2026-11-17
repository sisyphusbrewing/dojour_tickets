# Tuesday open mic sign-up

Free stand-up open mic every Tuesday at 7 PM in the comedy club (moved from the taproom, Sam, Nov 17 2026), from
Nov 17 2026. A few spots are booked ahead; the rest are drawn at random from
the online sign-ups (Sam, Nov 9 2026).

- `index.html` is the public sign-up form. It is embedded on
  sisyphusbrewing.com/pages/open-mic (iframe, sends its height with
  `micHeight`) and works on its own at staff.sisyphusbrewing.com/mic/.
  It calls `mic_signup()`, which puts the comic in for the next Tuesday.
  Sign-ups for a Tuesday close at 6:30 PM Central that day (moved from 5 PM, Sam, Nov 16 2026), then roll to the
  next week. One per email per week.
- `host.html` (staff login) is the host screen: pick the Tuesday, add the
  comics booked ahead, set how many open spots, tap Draw names. Booked comics
  go first, drawn ones after; Undo puts everyone back in the hat. Copy lineup
  puts the running order on the clipboard.
- The host and the 4 guaranteed spots (Sam, Nov 17 2026): on `host.html`
  staff type the night's host; that makes a private link to `picks.html`
  ("Send the link" opens the phone's share sheet). The host types up to 4
  comics there, 5 to 7 minutes each, no login, and can change them all day.
- The 6:30 draw (Sam, Nov 17 2026): at 6:30 PM, when sign-ups close, 12 spots
  fill: first-timers first ("the first timers automatically get up and should
  be identified online"; "it's 12 - First timers"), the rest drawn at random
  from everyone else, once (the staff page or the host's page,
  whichever is open, asks the database for it; `mic_draw()` only allows it
  from 6:30 on the day). Draw names on `host.html` still works by hand.
- Women's spots (Sam, Nov 17 2026: "some element of Gender balancing", "making
  an inference by name is okay"): each sign-up gets `women_spot`, a guess
  from the first name (`mic_guess_woman()`). It stays behind the scenes, on no
  page (Sam, Nov 17 2026: "This part of the sorting can be done behind the
  scenes"). The draw makes sure at least 3 of the 12 are women_spot
  comics, when that many signed up.
- Running order: the host opens, then a block of drawn names, then a
  guaranteed comic, then another block, and so on (12 drawn and 4 guaranteed
  = 3, guaranteed, 3, guaranteed...). `mic_renumber()` keeps it that way when
  anything changes. The host's page shows the whole order after the draw.
- At 6:35 PM the running order shows by itself at the top of `index.html`
  (so on the website's open mic page), stage names only (Sam, Nov 17 2026:
  "at 6:35 the list should automatically post online"). `mic_public_lineup()`.
- `hosts.html` (managers; Sam, Nov 17 2026: "a spot for Grace to put the open
  mic host and showcase hosts in to track them"): the next 10 weeks of
  Tuesdays and Thursdays, one host name each, saved in `mic_hosts` by date.
  Tuesdays also get the Send-the-link button.
- Data: `public.mic_signups`, `public.mic_hosts`, `public.mic_draws`;
  migrations `supabase/migrations/20261110003000_mic_signups.sql` and
  `20261117240000_mic_host_picks.sql`. Checks: `supabase/tests/mic_host_picks/`.

No emails go out yet; comics find out at the mic.
