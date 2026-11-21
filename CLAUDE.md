# Sisyphus tickets & staff tools

Read this first. It is the map of this repo for any Claude working on it.

Sisyphus is a brewery and 90-seat comedy club in Minneapolis, owned by Sam
Harriman. The public website is a Shopify store (sisyphusbrewing.com). This
repo is everything around it: the scripts that keep ticket counts honest, the
staff web pages, and the scheduled jobs that email people.

## What lives where

- **Python scripts at the top level** do the work. Each one starts with a
  docstring saying what it does; read that before the code. They run as
  GitHub Actions, never on a server.
- **`.github/workflows/`** runs those scripts, on a schedule (cron, in UTC) or
  by hand (`workflow_dispatch`). Most only need `pip install requests`.
- **Folders with an `index.html`** (`staff/`, `manager/`,
  `exchange/`, `advance/`, `payouts/`, `css/`, `sign/`, `home/`, the comic
  game folders, ...) are static pages served by GitHub Pages at
  **https://staff.sisyphusbrewing.com/** (see `CNAME`). Merging to `main`
  publishes them. Shared styles and helpers: `staff.css`, `staff.js`.
- **`supabase/`** is the database (project `idsdwkubqnavkazlteis`):
  `migrations/` for tables and policies, `functions/` for Edge Functions.
  Apply migrations and deploy functions with the Supabase connector; committing
  a file here does not deploy it.
- **`theme/`** is a partial copy of Shopify theme files for reference and for
  building a duplicate theme. It is not the live site.
- **`tools/`** holds one-off diagnostics (read-only probes).
- **Website pages kept here:** `mic/shopify-page.html` (Open Mic page) and
  `pages/*.html` hold the text of Shopify pages (Online Store > Pages, not
  the theme). Merging a change pushes it live through `shopify_pages.py`
  (workflow "Shopify pages"). Edit the file, not the page in Shopify, or the
  next merge overwrites the edit. As of Nov 17 2026 the repo's Shopify app
  lacks the `read_content`/`write_content` scopes, so that workflow fails
  with ACCESS_DENIED; until Sam adds them, push the same text with the
  Shopify connector (`pageUpdate`) and check the live page matches the file.

## The ticket flow (the core of the repo)

Tickets sell in two places that share the same seats: Shopify (the website)
and Dojour. Counts always mean Shopify + Dojour together.

- `fetch_tickets.py` pulls sales from both into Supabase.
- `sync_inventory.py` mirrors Dojour sales into Shopify inventory so the
  website never oversells. Stock is capped at 90.
- `dojour_holds.py` blocks website-sold seats on Dojour with "Website Hold"
  reservations. Dojour's 90-seat cap is shared across a run's showtimes, so
  per-show blocking has to be done with holds.
- `daily_sync.yml` runs the sync every 4 hours.
- **The website fee is $4** since Nov 18 2026 (Sam OKed the preview): $3 to
  the host and feature as before, $1 to cover card processing. It is inside
  the price (all-in pricing). `ticket_fee.py` holds it; each show's product
  carries `custom.card_fee` and `custom.card_fee_since`, so settlements and
  swaps know which tickets were sold at the old $3. The $1 is never door or
  comic money. Advice Column stays at $3 (Sam's pick).

Dojour gotchas, learned the hard way:
- Dojour **rejects add-reservation calls made by scripts** ("You do not have
  permission"), from GitHub, the office PC and Sam's Mac alike, but accepts
  them through the dashboard in Sam's own signed-in Chrome. So
  `dojour_holds.py` only plans, and a Claude scheduled task ("Dojour seat
  top-up", 7:43 AM and 4:43 PM Central, since Nov 18 2026: Sam, "Dojour seat
  blocks are supposed to be automated") runs the plan and adds the holds in
  his Chrome. The 8:20 AM GitHub run emails Sam only if seats are still open
  (his Mac was asleep). Don't try to make a script imitate a browser. Reading from Dojour
  works from anywhere.
- Sam's own Dojour holds (rows with no buyer email, e.g. "Shopify Sales")
  are not sales. Leave them out of any sales or agent count; agents read every
  number as paid tickets.
- `DOJOUR_STATE` is a saved browser login (Playwright storage state);
  `login_setup.py` makes it.

## The staff site (staff home, top bar, schedule)

- **`staff/tools.js` is the one list of staff tools.** The staff home page
  draws its tiles from it and the top bar (`staff/nav.js`) draws its "All
  tools" menu from it. A new tool is one new entry there, with the lowest
  login that may open it. A tool that opens to more people on a set day
  takes `opens` (the day) and `early` (who may use it before then). No tool
  uses them now: the Clock was held back that way until Sam opened it to
  everyone on Nov 17 2026.
  A staff page gets the top bar with one line:
  `<script src="/staff/nav.js"></script>`. Don't put the bar on pages
  customers or comics see (exchange, payme, the Shopify embeds).
- **The staff home page is `staff/index.html`** (live since Nov 17 2026, Sam:
  "Let's launch the new staff portal and the scheduler"): tonight's show,
  your next shift, What's new, the tools, what's coming up. `staff/new.html`
  was its preview and now only forwards there. "Tonight" and "Coming up" put
  two lists together: the show calendar (`schedule_needs()`, the same one the
  Schedule reads, free nights included) and ticket totals
  (`staff_show_counts()`). A free night is a show night and reads "Free"
  (Sam, Nov 17 2026: "There is a show tonight - the free mic", when the page
  only knew shows that had sold a ticket). The shared door login isn't given
  the calendar, so it sees ticketed shows only. `exchange_ticket.py --refresh`
  keeps a showtime on the calendar for six hours after it starts, so tonight's
  show doesn't drop off the page in the middle of the show.
- **`staff/look.css` is the simpler look** (Sam, Nov 15 2026: "simple and
  easy for people to read and use"). A page uses it by loading it after
  `staff.css` and putting `class="look"` on its `<body>`. Build new staff
  pages on it: big plain text, plain headings, one box per list with thin
  lines between rows, one bright button per box. The staff home page and the
  Schedule use it; older tools move over one at a time, checked on a phone.
- **`schedule/`** is the staff schedule that replaces When I Work (Sam, Nov 14
  2026). The rules (who sees drafts, who can take a shift, who gets told)
  live in the database, in `supabase/migrations/20261115040000_staff_schedule.sql`;
  the page only shows and asks. Every change that affects someone writes a
  row to `schedule_outbox`; `schedule_notify.py` sends those by email or text,
  whichever that person picked. GitHub drops most runs of a job that is
  scheduled every few minutes here (it started "Schedule notices" 2 to 4
  times a day instead of 68), so that workflow is one long run that looks
  every two minutes and starts its own next run when it ends, with the
  schedule as a backup. Pages don't start it. If notices stop, start it once
  by hand (Actions > Schedule notices > Run workflow). It sends nothing
  between 1 and 8 AM Central. Check rule changes with
  `supabase/tests/staff_schedule/` before applying them.
- **The Schedule says how many people each day needs** (Sam, Nov 17 2026:
  "The scheduler should read the calendar for upcoming events and then say
  how many people we need to schedule because of it"). The calendar is
  `exchange_showtimes`, the website's upcoming showtimes (free nights are on
  it at $0), rewritten by the sync every four hours. `schedule_needs()` in
  `supabase/migrations/20261117200000_staffing_needs.sql` works out each
  day's number: people on while we're open, more for a ticketed show or a
  free event, counted from 90 minutes before, or from an hour before when
  it starts at 6 PM or earlier (Sam, Nov 17 2026: "When we have a 6pm show
  the bartender shifts should start at 5pm rather than 5:30"; the current
  `schedule_needs()` is in
  `supabase/migrations/20261117230000_early_show_start.sql`). Managers see "Needs 3 people, 1
  scheduled" on each day, can change the numbers in a box under the week, and
  can set one day by hand (a holiday, a private party). The starting numbers
  came from three months of When I Work clock-ins and are Sam's to change.
  Checks: `supabase/tests/staffing_needs/`.
- **The Schedule has a usual week**, the template a week is built from (Sam,
  Nov 17 2026: "Can we pull up when i work so you can see what our schedules
  were like before and we can use that as the template going forward?"). It
  is a short list of shifts by day of the week with who usually works each
  one, worked out from When I Work's old schedules and clock-ins. Managers
  tap "Fill the usual week" on the Schedule and those shifts land on the week
  on screen as drafts: days that are over, already have a shift, or are set
  by hand to nobody are left alone, and a shift is left open when its person
  has that day off. "Save this week as the usual week" (in the box under the
  week) replaces it; the old one is kept, marked replaced. The rows are
  people's names and hours, so they live only in the database
  (`usual_shifts`), never in this repo. Rules in
  `supabase/migrations/20261117290000_usual_week.sql`, checks in
  `supabase/tests/usual_week/`.
- **A staff login can be marked "builds the schedule"** (Sam, Nov 18 2026:
  one of the bartenders "wants to take over making the schedule"). A manager
  login opens far more than the Schedule (Payroll's hours and tips, the
  Manager page with the staff logins, booking, supply orders), so this is a
  mark on a staff login instead. On the Schedule that login does what a
  manager does: drafts, posting, the usual week, a day's number set by hand,
  names and who is on the schedule, and answering time off (never its own; a
  manager answers that one). It is told the schedule's news that managers
  are told, but not the time clock's. Everywhere else it is still a staff
  login, and the box of staffing numbers stays with managers. The mark is
  `staff_roles.builds_schedule`, set in the database on Sam's word; there is
  no button for it, and who carries it is not written in this repo.
  `can_schedule()` is the question the Schedule's rules ask now: a new
  version of one of the Schedule's functions should ask it, not
  `is_manager()`. Rules in
  `supabase/migrations/20261118060000_schedule_builder.sql`, checks in
  `supabase/tests/schedule_builder/`.
- **`clock/`** is the time clock (Sam, Nov 16 2026: "people enter their shifts
  tied to the scheduler" and "clock in and out via tap with their phones").
  All staff use it since Nov 17 2026 (Sam: "they will be tracking their tips
  on that page as well, no more go-tab for clocking in and out"). It
  replaces When I Work's time clock and the "Tip Tracker" Google Sheet: an
  NFC tag at the bar that clocks a phone in or out when the phone is held
  to it (Sam, Nov 17 2026: "I would rather do nfc tap for clock in and out vs
  QR code"; the page's one big button does the same for a phone that can't
  tap), the night's credit tips typed per shift, "My
  hours" for the two-week pay period (Monday to Sunday twice, counted from Mon
  Nov 2 2026), and a Payroll tab for managers with hours and tips per person,
  last name first, the way Sam types them into ADP. The rules live in
  `supabase/migrations/20261117060000_time_clock.sql`; the page only shows
  and asks. Nothing is ever deleted (a removed shift is flagged), paid hours
  and paid tips are locked, and only the owner marks a payroll submitted. The
  link on the bar's sticker carries a code kept in the database
  (`clock_settings`), never in this repo. A tap clocks in at once (undo for
  two minutes) and clocks out after a four-second "Not yet" wait; nothing
  happens by itself within two minutes of the last punch, so a double read
  can't undo it. Without the tag, the big button only works on the club
  wifi (Sam, Nov 17 2026: "People can also clock in and out on their phone
  but they have to be connected to our wifi to do so"): the database compares
  where the request came from with the club's network, which a manager sets
  once from the Payroll tab ("The club wifi") while standing in the club.
  Until that is set the rule is off. That rule is in
  `supabase/migrations/20261117210000_clock_wifi.sql`. Clocking in, by the
  tag or by the button, first walks the person through any "What's new"
  updates they haven't read, one at a time, and "Got it" on the last one
  clocks them in (Sam, Nov 17 2026: "they should have to click through the
  updates before they can clock in"). Only updates posted since Nov 17 2026
  count (and since the login was made, for a new hire). This one is the
  page's doing, not the database's, on purpose: if the updates can't be
  loaded or a "Got it" can't be saved, nobody is kept off the clock.
  Clocking out never waits on it. Its notices ride the schedule's
  outbox (kinds starting `clock_`). Check rule changes with
  `supabase/tests/time_clock/` before applying them.
- **`doorshift/`** is the "I worked the door" form (Sam, Nov 17 2026: "We
  need a seperate form where people can submit if they worked the door"). The
  people at the door are mostly comics, not on the time clock or the payroll,
  and have no login of their own, so the page needs none (like `payme/`) and
  has no staff top bar. They pick the night, leave a name and a Venmo
  username, and it lands on the pay sheet (`payouts/`, owner only) under
  "Asking to be paid", marked Door. The form asks for no amount and sends
  none: what a door shift pays is Sam's to type when he approves, and the
  sheet offers what the last door shift on it was paid. Keep pay rates out of
  this repo; it is public. One per night; the pay sheet never mixes a door
  shift up with a comic's pay for the same show. It has no
  table of its own: it uses `pay_request()` and `pay_shows()`, the same two
  database calls as `payme/`, and booking@ gets the same email
  (`pay_request_notify.py`, worded for a door shift). The Door page links to
  it.
- **`booking/`** is the Booking board (Sam, Nov 14 2026, built for Grace):
  every weekend at a glance, what each show still needs (contract, W-9, host,
  feature, advance, emails) and the booking requests waiting for an answer.
  Almost all of it is read from what we already keep (show nights, ticket
  counts, advances, the pay sheet, comic scores, tap-card pitches) through one
  database function, `booking_board()`. Its own tables are `booking_shows`
  (dates pencilled in, host/feature, boxes ticked by hand) and
  `booking_threads` (one row per conversation in the booking@ inbox).
  `booking_inbox.py` fills `booking_threads` every hour by reading booking@
  over IMAP, read-only; it never sends, labels or marks anything.
  Each show on the board also has **"Every show needs"** (Sam, Nov 18 2026:
  manager, openers, rider, the emails for video, ticket updates and the
  settlement, how they get paid, the artist has the advance; "This is just
  the start"). The list is `SHOW_NEEDS` in `booking/index.html`: a new line
  is one entry there. Typed answers live in `booking_shows.info`; lines
  something else knows (the advance, the weekly report's `show_agents`,
  where the video went) fill themselves in, and a gap is flagged from three
  weeks out. The ticket update email is `show_agents` itself, and an email
  for the video typed there is where `recording_mail.py` sends it.
- **The events@ inbox is read the same way** (Sam, Nov 17 2026: "We should
  probably do this for the events@ email as well"). events@ is where the
  public writes and nobody owns it, so things sit. `events_inbox.py` (workflow
  "Events inbox", hourly) reads it with the same read-only reader as
  `booking_inbox.py` and keeps one row per conversation in `events_threads`:
  what it is (a private event or group, a ticket problem, an accessibility
  question, a donation request, a comic who belongs in booking@, a sales
  pitch), the dates and headcount they mentioned, and whose turn it is.
  Managers only. It never sends, labels or marks anything either, and both
  readers print counts only.
  The one exception is `inbox_trash.py` (workflow "Inbox trash", by hand
  only): it moves conversations Claude names in events@ or booking@ to Trash,
  never a permanent delete, and refuses any conversation someone at
  Sisyphus wrote in (Sam, Nov 18 2026: "it would be nice to not have to
  deal with stuff that is obvious trash ... In all 3 inboxes"). Managers work the list on **`inbox/`** (the
  "Events inbox" tile): To answer, Waiting on them, Done, with Open in Gmail,
  Done and Later on each; sales pitches sit folded at the bottom. Lease and
  press emails (kinds `owner`, `press`) are the owner's alone: the database
  never hands them to a manager login. Checks: `supabase/tests/events_inbox/`.
- **Reorder buttons** sit at the top of `supplies/` (Sam, Nov 17 2026: "it
  would be nice to have buttons to order stuff like that, Pretzels"). Each is
  the usual order email to one vendor (pretzels Von Hanson's, jerky Ye Olde
  Butcher Shoppe, sodas and Liquid Death Capitol Beverage, syrups Sweet Haven,
  seltzer ABV, kombucha J's), kept in `supply_reorders`. A manager taps Order,
  ticks each kind in or out (each pretzel flavor, each soda) and changes
  counts with − and +, taps Send; `place_reorder()` writes `supply_orders` (only
  counts change, never items or addresses; the same order twice in three days
  asks first) and `supply_notify.py` emails it from ticketing@ with sam@ and
  booking@ copied, replies to Sam. Rules in
  `supabase/migrations/20261117220000_supply_reorders.sql`, checks in
  `supabase/tests/supply_reorders/`.
- **`safe/`** is "Say something", for reporting unsafe behavior (Sam, Nov 17
  2026: "Let's make some thing for the Green Room where people can tap or go
  to a website if they need to report unsafe behavior"). No login, name
  optional, no staff top bar. Opened by the NFC tag on the Green Room sign
  (`?via=tag`), its QR code (`?via=qr`) or the link. `safety_report()` saves
  it (`supabase/migrations/20261117270000_safety_reports.sql`; only the
  owner login and the service key can read reports) and `job-applied` kind
  `safety` starts `safety_notify.py`, which emails Sam (sam@), Grace
  (booking@) or both, the reporter's pick, so someone can report about
  either of them. The Booking board skips these emails. The page promises
  nothing about the phone is kept (no address, nothing saved on the phone):
  keep that true. The sign is made by `safe/make_sign.py`.
- **`gift/`** is the tap gift cards (Sam, Nov 17 2026: "I want to offer gift
  cards now with the NFC chip writing ability"; spent at the club only, not
  on the website, Sam's pick). Each blank NFC card carries one link,
  `/gift/?c=<32 random letters>`, written with NFC Tools. A guest's tap shows
  the balance only; any signed-in staff login can Take off and Put on (Sam,
  Nov 17 2026: staff sell cards at night on a phone kept at the bar, where
  Android Chrome reads each card into the open page), each can undo their
  own change for two minutes. The
  balance is the sum of `gift_card_moves`; nothing there is ever changed or
  deleted (a trigger refuses it), and a lost card is switched off with its
  money moved to another card. GoTab can't read the cards: staff ring the
  sale and the payment in GoTab and do the balance on the page. Minnesota
  gift cards can't expire or carry fees. Rules in
  `supabase/migrations/20261118000000_gift_cards.sql`, checks in
  `supabase/tests/gift_cards/`. **`station/`** is the Boulder, the touch
  screen at the front bar (Sam, Nov 18 2026): an ESP32 screen board with a
  PN532 reader (wired in serial mode; on I2C it clashes with the board's own
  chip) that makes a new card from a blank in one go (`gift_card_new()`,
  write, read back, lock, load) and does Add and Take off for any card.
  PlatformIO; the club wifi goes in a gitignored `secrets.h`, and the
  station signs in with its own staff login typed on the screen.
- **`night/`** is "Your night", the guest's page, and the first piece of our
  own point of sale (Sam, Nov 18 2026: "let's focus on building our own
  system that we can switch over to" and "I want to focus on the customer
  experience from check-out, through arrival, to that first beer and knowing
  what is going on. Helping people get comfortable in a new space quickly is
  key"). One phone page: a blue box that says what is happening right now
  (doors in 40 minutes, doors are open, you're in, the show's on), the night
  in five steps with "You are here" on the guest's step, and the tap list.
  A guest with tickets can pick a first beer, one per ticket; it costs
  nothing to pick and is paid at the bar. **`firstround/`** is the bar's
  list: a pick moves to "Pour now" when the door checks its guest in. No
  login for guests and no staff top bar on `night/`: `?k=<key>` is a guest's
  own link, no key shows only tonight's show, "Find my tickets" (email and
  last name) gets a key, and `?preview=1` walks a made-up guest through the
  night and saves nothing. **Guests are not sent this page yet** and the
  First round tile is owner only; don't email the link, put it on a tag or
  open the tile to staff until Sam says so. The words on the page are a
  first pass for Sam to change. Doors are taken as 30 minutes before
  showtime (the website's FAQ); a second show of the night never promises a
  door time. Rules in `supabase/migrations/20261119030000_guest_night.sql`,
  checks in `supabase/tests/guest_night/`. The bartender's register (tabs,
  payments, our own card reader) is the next piece, not built here.
- **`backup/`** is the nightly backup on the office PC (Sam, Nov 18 2026:
  "Can we use my PC currently as a back up?", until a NAS arrives). restic
  snapshots of the recordings, OBS and Companion settings, this repo and a
  dump of the database (read-only login `backup_reader`, Sam OKed Nov 18
  2026), 3:15 AM, in `C:\SisyphusBackup\restic` until the PC's 2 TB second
  drive gets a partition (needs one admin click at the PC). The task runs
  `run-backup.ps1`, which pulls `nightly.ps1` and `heartbeat.ps1` from main
  first. The PC checks in every 10
  minutes (`device_heartbeat()`, which also puts its power settings back to
  never sleep) and `schedule_notify.py` emails Sam when it goes quiet for 30
  minutes, comes back, or a backup fails or is missed. Rules in
  `supabase/migrations/20261119040000_device_heartbeats.sql`. The restic
  password, the database password and the check-in code live only on the PC.
- **Printed checks for comics** (Sam, Nov 18 2026: "Need secure checks for
  printing at the taproom for comedians, can only work on my approval"; he
  picked a printed signature). On the pay sheet (`payouts/`), a line paid by
  Check gets "Print check"; the Checks tab is the register. Only the owner
  login approves (`check_approve()`); a trigger refuses any other way to
  approve, even with the service key. The office PC (`backup/checks/`,
  installed once at the PC by `setup-checks.ps1`, never auto-updated) prints
  approved checks every minute on its own small Brother (MICR toner, so the
  office Brother keeps normal toner; Sam prints a lot) and blank check stock, marks the
  line paid, and keeps a positive-pay file. The routing and account numbers
  and Sam's signature live only on that PC (Windows-encrypted), never in the
  database or this repo. Nothing is deleted; a voided number is never reused;
  every step is in `check_events`. `schedule_notify.py` emails Sam when a
  check waits for him, prints, fails or sticks. Rules in
  `supabase/migrations/20261119060000_comic_checks.sql`, checks in
  `supabase/tests/comic_checks/`.
- **Walk-on songs** (Sam, Nov 19 2026: "Before a show we should let comics pick
  a walk up song and we can integrate that into the deck"; he picked Spotify
  Premium on the office PC). Host, feature and headliner each pick on
  **`walkon/`** (`?s=<token>`, no login, no staff top bar; one link per run,
  copied from the Booking board's "Walk-on songs" line), and the headliner
  can also pick on the advance trip's last stop. Both use `walkon/song.js`
  (Apple's public song search, a 30-second listen, a start point). The song
  belongs to the comic and carries over to their next show. On show night
  the office PC helper `av/walkon/walkon.py` (port 8793, set up by
  `av/walkon/setup.ps1`, Spotify's key only in `%USERPROFILE%\.sisyphus\spotify.json`)
  reads `walkon_tonight()` and plays each song on the PC's Spotify; the deck's
  SHOW screen has WALK-ON and AFTER where the open mic's ON NOW and UP NEXT
  sit (open mic nights keep those). Rules in
  `supabase/migrations/20261119230000_walkon_songs.sql`, checks in
  `supabase/tests/walkon/` and `test_walkon.py`.
- **Show recordings** are cut on the office PC at 4 AM by
  `av/recordings/split_and_share.py` (one clip per comic, uploaded to Drive,
  a row each in `recordings`); `recording_mail.py` emails the links at 9 AM.
  The Task Scheduler task runs the plain local file
  `av/recordings/run-recordings.ps1`, which pulls the newest script and runs
  it. **A scheduled task on the office PC must only ever run a local file
  (`powershell -File ...`).** On Nov 20 2026 Microsoft Defender judged the
  old task, one hidden PowerShell line that downloaded the script from GitHub
  and ran it, to be malware and blocked it; nothing was cut that night and
  nothing said so. When a task there silently does nothing, read Defender's
  log first. Don't add Defender exclusions. The backup does the same:
  its task runs `backup/run-backup.ps1` (Nov 20 2026).
- **Wyze cameras** (Sam, Nov 20 2026: "Do Wyze cams integrate?" ... "Yeah set
  that up"). `av/cams/setup.ps1` installs go2rtc on the office PC (one Windows
  program, no Docker; it talks to the cameras directly on the club network).
  Sam adds his Wyze login and API key on go2rtc's own page on that PC; they
  stay in `%USERPROFILE%\.sisyphus\go2rtc.yaml`, which Claude never opens.
  Everything listens on 127.0.0.1 only, so nothing reaches either Wi-Fi. The
  task "Sisyphus cameras" runs the local `run-cams.ps1`, which keeps it up.
  Uses: OBS Media Source `rtsp://127.0.0.1:8554/<name>`, and
  `still.ps1 -Cam <name>` (or `-All`) for a picture in
  `sisyphus-av\cams\stills\`, e.g. to check the taproom lights after a look.
  Wyze OG and Pan v4 cameras don't work with it.
- **Hubspace lights** (Sam, Nov 20 2026): the LED string light over the sink
  area is Hubspace (Home Depot), not Govee, and has no official API. The
  office PC runs `av/hubspace/hubspace.py` (127.0.0.1:8794, started at logon
  by the "Sisyphus Hubspace helper" task running the local
  `run-hubspace.ps1`), which uses Hubspace's cloud through `aioafero`. Sam's
  login lives only in Windows Credential Locker ("sisyphus-hubspace"); he
  stores it himself with `set-login.ps1`. The deck's looks call
  `/set?name=Comedy&...` (`SINK_LOOK` in `build_companion_config.py`).
- The door page (`index.html`) keeps working with no internet (Nov 18 2026):
  it saves tonight's lists on the phone, queues check-ins and sends them when
  the connection is back; `door-sw.js` keeps the page opening offline.
- This repo is public, so are its Actions logs. Scripts must not print staff
  names, email addresses, phone numbers or message text.

## Secrets

Workflows read secrets from GitHub Actions: `SHOPIFY_STORE`,
`SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` (or `SHOPIFY_ACCESS_TOKEN`),
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SMTP_HOST/PORT/USER/PASS`,
`FROM_EMAIL`, `DOJOUR_STATE`, `BOOKING_IMAP_PASS` (an app password for the
booking@ inbox, read by `booking_inbox.py`), `EVENTS_IMAP_PASS` (the same for
events@, read by `events_inbox.py`), and (for schedule texts, once set
up) `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`. Never print or commit their values.
`service_account.json` and `state.json` are gitignored for that reason.

## How to work here

1. **Find the real cause before fixing anything.** Read the failing
   workflow's log, the script, and the live data (Supabase, Shopify, the
   page itself) first. Don't guess and don't hand Sam trial-and-error steps.
   One fix per cause.
2. **Prove it works before saying it's done.** Run the tests, run the script
   in dry-run mode if it has one, open the page in Playwright on desktop and
   phone width, or query the data that should have changed. Say what you
   checked. "Should work" is not done.
3. **Tests:** `python -m unittest test_exchange_ticket test_settlement_draft test_sync_inventory test_dojour_refund test_split_and_share test_advance_auto test_voice_notes test_sales_by_day test_door_list_keep test_agent_reports test_dojour_holds test_door_count test_deck_music test_deck_lineup test_deck_recording test_schedule_notify test_booking_inbox test_events_inbox test_shopify_pages test_pay_request_notify test_supply_orders test_safety_notify test_comic_ads_refresh test_inbox_trash test_recording_mail test_ticket_fee test_walkon`.
   They also run on every pull request. Tests must not depend on today's date;
   build show dates relative to now. Never skip or delete a test to go green.
   Money math, ticket counts and anything that emails customers deserve a test.
4. **Pull requests:** work on a branch, open a PR, and merge it yourself once
   checks pass. Sam does not merge.
5. **Staff-facing change** (new page, new button, new process)? Add a row to
   the `staff_updates` table so staff see it in "What's new" on `/staff/`, and
   add a tile to the staff hub for any new tool.
6. **The live Shopify theme is off limits** to direct edits. Duplicate the
   live theme, edit the copy, check it, and give Sam a preview link and the
   theme name to publish.
7. **Never email or message anyone outside Sisyphus** from a new script
   unless Sam asked for it. Scheduled emails go to booking@ or to the person
   they're about.

## Style

Code comments and emails are plain English for a non-programmer owner: say
what the thing does and why, with the date and "(Sam, <date>)" when it records
one of Sam's decisions. Keep scripts self-contained and dependency-light.
Times in workflows are UTC; note the Central time in a comment.
