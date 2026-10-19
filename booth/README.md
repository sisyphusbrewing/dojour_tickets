# Photo booth

Every ticket gets one photo booth strip. The guest holds their ticket QR up
to the camera (or types the email on their ticket), the booth shoots four
frames, shows the strip, asks how many strips (up to what's left on the
order), and prints. Each 4x6 print is cut by the printer into two 2x6 strips.

Page: https://sisyphusbrewing.github.io/dojour_tickets/booth/

## How the pass works

The booth is the first of the **ticket experiences**
(`supabase/migrations/20261019060000_experiences.sql`). Every experience
uses the same two calls:

- `exp_scan(p_key, p_experience, p_code)`: `p_code` is the scanned QR text or
  the ticket email. Finds tonight's order, returns the show, the guest's first
  name, how many uses are left, and a pass id. Reasons it can say no: `key`,
  `closed`, `no_ticket`, `used`.
- `exp_redeem(p_key, p_pass, p_uses)`: settles the pass (the booth sends the
  number of strips). Capped at what the order has left.

Uses per experience = tickets on the order, so a party of four gets four
strips. A scan that never redeems holds one use for 10 minutes, then lets go.
The QR match looks for our ticket id (or the Dojour/Shopify id inside it)
anywhere in the QR text.

Add an experience: `insert into experiences (slug, name) values ('fortune', 'Fortune machine')`,
then call the same two functions with that slug. Turn one off with
`update experiences set active = false where slug = '...'`.

Experience screens aren't staff logins. Each machine has a device key in
`experience_devices` (only the sha256 is stored). Add one:

```sql
insert into experience_devices (key_hash, label)
values (encode(extensions.digest('<new key>', 'sha256'), 'hex'), 'Fortune machine');
```

The log of every use is `experience_uses` (managers only).

## Hardware

| Part | Pick | About |
|---|---|---|
| Printer | DNP DS-RX1HS (4x6 with 2-inch cut) | $1,000 |
| Paper | DNP RX1 4x6 media, 2 rolls = 1,400 prints = 2,800 strips | $220 (8¢ a strip) |
| Computer | Small Windows mini PC (DNP's drivers are best on Windows) | $250 |
| Screen | 15 to 22 inch touch monitor, portrait or landscape | $150 to $250 |
| Camera | Logitech Brio or C920 webcam, mounted just above the screen | $70 to $150 |
| Light | LED ring or soft panel behind the screen, daylight | $60 |
| Shell | Built by Sam. Leave a slot under the screen for the strips. | |

## Setup

1. Install the DNP driver. In the printer's preferences set paper to **4x6**,
   turn on **2-inch cut**, and make it the default printer. Print a test page.
2. Make a Chrome shortcut that starts on boot (shell:startup):

   ```
   chrome.exe --kiosk --kiosk-printing --use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required "https://sisyphusbrewing.github.io/dojour_tickets/booth/?key=<device key>"
   ```

   `--kiosk-printing` prints straight to the default printer with no dialog.
   `--use-fake-ui-for-media-stream` lets the camera on without asking. The
   key is remembered after the first start, but leaving it in the shortcut is fine.
3. Tap the top-right corner five times for settings: pick the camera, paste a
   device key, or run **Test run** (unlocks without a ticket, prints a strip
   that says Booth Test). Typing `test` as the email does the same.
4. In Windows, turn off sleep, screen saver and notifications.

## The strip

2x6 at 300 dpi (600x1800). Four 3:2 frames, mirrored like the preview, on
charcoal; under them the show name on the tilted slate band, the date,
SISYPHUS, and "One must imagine Sisyphus happy." No logo badge until the new
one is approved.
