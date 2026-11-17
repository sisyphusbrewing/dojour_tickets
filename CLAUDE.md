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

Dojour gotchas, learned the hard way:
- Dojour **rejects add-reservation calls made by scripts** ("You do not have
  permission"), from GitHub, the office PC and Sam's Mac alike, but accepts
  them through the dashboard in Sam's own signed-in Chrome. So
  `dojour_holds.py` only plans (daily) and emails Sam; holds get added in his
  Chrome. Don't try to make a script imitate a browser. Reading from Dojour
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
  takes `opens` (the day) and `early` (who may use it before then); the
  Clock is a manager's tool until Mon Nov 30 2026 and everyone's from then.
  A staff page gets the top bar with one line:
  `<script src="/staff/nav.js"></script>`. Don't put the bar on pages
  customers or comics see (exchange, payme, the Shopify embeds).
- **The staff home page is `staff/index.html`** (live since Nov 17 2026, Sam:
  "Let's launch the new staff portal and the scheduler"): tonight's show,
  your next shift, What's new, the tools, what's coming up. `staff/new.html`
  was its preview and now only forwards there.
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
- **`clock/`** is the time clock (Sam, Nov 16 2026: "people enter their shifts
  tied to the scheduler" and "clock in and out via tap with their phones"). It
  replaces When I Work's time clock and the "Tip Tracker" Google Sheet: an
  NFC sticker at the bar that clocks a phone in or out when the phone is held
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
  can't undo it. Its notices ride the schedule's
  outbox (kinds starting `clock_`). Check rule changes with
  `supabase/tests/time_clock/` before applying them.
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
- This repo is public, so are its Actions logs. Scripts must not print staff
  names, email addresses, phone numbers or message text.

## Secrets

Workflows read secrets from GitHub Actions: `SHOPIFY_STORE`,
`SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` (or `SHOPIFY_ACCESS_TOKEN`),
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SMTP_HOST/PORT/USER/PASS`,
`FROM_EMAIL`, `DOJOUR_STATE`, `BOOKING_IMAP_PASS` (an app password for the
booking@ inbox, read by `booking_inbox.py`), and (for schedule texts, once set
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
3. **Tests:** `python -m unittest test_exchange_ticket test_settlement_draft test_sync_inventory test_dojour_refund test_split_and_share test_advance_auto test_voice_notes test_sales_by_day test_door_list_keep test_agent_reports test_dojour_holds test_door_count test_deck_music test_schedule_notify test_booking_inbox test_shopify_pages`.
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
