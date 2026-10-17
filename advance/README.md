# Comedian advance

The form comedians and agents fill out before a show, and the desk where
booking reads the answers. Served by GitHub Pages:

    form:  https://www.sisyphusbrewing.com/pages/advance?s=<token>
    desk:  https://sisyphusbrewing.github.io/dojour_tickets/advance/booking.html

The form itself is served from this repo at `advance/index.html`; the Shopify
page "Advance" (handle `advance`) embeds it in an iframe and passes the query
string through, so comedians only ever see sisyphusbrewing.com. The page body
is in `advance/shopify-page.html`.

## How it works

1. On the desk (same staff sign-in as the door app) press **New advance**,
   type the show name, date and time, and who it is going to. That makes a
   link that only opens that show.
2. **Email it** opens a ready-made email with the link; **Copy link** if you
   would rather text it. Nothing is sent until you send it.
3. The comedian fills in the form on their phone: name, promo (headshot, bio,
   socials, a clip), travel and hotel, stage needs, intro, guest list, merch,
   and how they want to be paid. Answers save on their device as they type,
   and the same link lets them come back and change things.
4. When they press **Send it**, booking@sisyphusbrewing.com gets an email
   with the answers and the headshot attached, and the desk shows it under
   **Sent in**.
5. On the desk you can copy the bio or the intro, open the headshot, copy
   everything as plain text, keep staff notes, and **Create show tickets**,
   which runs the same Shopify pipeline as the door app with their bio and
   headshot already filled in.

Someone without a link can open the form bare and type the show name
themselves; it shows up on the desk like any other.

## Fields

All three pieces (form, desk, email) read the one list in `fields.js`. Add,
reword or reorder a field there and everything follows. The value after the
`=` is plain JSON so `advance_notify.py` can read it too.

## Data

* `public.advances` (migration `supabase/migrations/20261014235000_advances.sql`):
  one row per advance; the answers live in `data` (jsonb) keyed by the field
  `k`. Staff and the service key have full access. The public form only goes
  through `advance_get`, `advance_open` and `advance_submit`, which need the
  token.
* Storage bucket `advance` (public read): headshots at `<token>/<file>`.
  Uploading needs a valid token; only staff can replace or delete.
* Edge function `advance-submitted` (`supabase/functions/advance-submitted/`):
  the form calls it after submitting. It checks the token and starts the
  **Comedian advance** action (`.github/workflows/advance_notify.yml`), which
  runs `advance_notify.py` and emails booking@. It uses the same `GITHUB_TOKEN`
  secret as `run-workflow`. Set the repo variable `ADVANCE_EMAIL_TO` to change
  who gets the email.

## The welcome and the trip

When a comedian is booked, the desk's **Send the welcome** button emails
them a short "you're booked" note from Sam (`advance_welcome.py`, action
**Comedian welcome**, started through `run-workflow`; it Bccs booking@ and
stamps `welcome_sent_at`). Its button opens `trip.html`: the same advance,
one quick stop at a time up the hill (green room, security, guest sets and
everything the one-page form asks). Each stop saves with `advance_trip`
(merges into `data`); the last stop sends it in with `advance_submit` like the
form. `trip.html` with no `?s=` is a preview that saves nothing.

Preview the email anywhere: run **Comedian welcome** with `to` filled in.
