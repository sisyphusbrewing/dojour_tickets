# Stage timer

Comic-facing stage clock (counts up from 0:00) at https://staff.sisyphusbrewing.com/timer/

Open it full screen on whatever screen the comic can see (a TV on the back wall,
or a tablet at the stage edge). Black screen, only the digits glow, so it
doesn't light the room. The digits count up from 0:00 (a countdown makes comics
panic), turn red with LIGHT at one minute left, say WRAP IT UP at 30 seconds left, and
over time say "You better know what you are doing....", then "No seriously.... are you
famous?" a minute over. Time of day sits small at the top.
It keeps the screen awake. Tap the screen for buttons (5/7/10/15/20 min, +/-1, Wrap it up, Stop);
they hide again after 10 seconds.

State is one row in Supabase (`stage_timer`, migration
`supabase/migrations/20261016220000_stage_timer.sql`). Every screen counts from
the server clock and updates the moment anything presses a button.

## Stream Deck buttons (Companion, Generic HTTP POST)

All are `POST https://idsdwkubqnavkazlteis.supabase.co/rest/v1/rpc/<name>` with
header `{"apikey": "<publishable key>"}` and content type `application/json`,
same as the MENU REFRESH button.

| Button | rpc | body |
|---|---|---|
| 5 MIN / 7 MIN / 10 MIN / 15 MIN | `timer_start` | `{"minutes": 5}` etc. |
| AGAIN (last length) | `timer_start` | `{}` |
| +1 MIN | `timer_add` | `{"seconds": 60}` |
| LIGHT (toggle by hand) | `timer_light` | `{}` |
| STOP | `timer_stop` | `{}` |
| Light at N min left | `timer_set_light` | `{"minutes": 2}` (default 1, 0 = off) |
