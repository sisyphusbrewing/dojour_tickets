# The Boulder (gift card station)

The touch screen at the front bar that makes and reads the tap gift cards
(Sam, Nov 18 2026). It does what `/gift/` does on a staff phone, plus making
a new card from a blank in one go:

1. **New card**: tap New card, type the amount, set a blank card on the
   boulder. The station makes the card (`gift_card_new()`), writes its link,
   reads it back, locks it, and puts the money on (`gift_card_load()`). Then
   it says: ring that amount on the "Gift card" item in GoTab.
2. **Any gift card**: set it on the boulder to see its number and balance,
   then Add or Take off. Undo works for two minutes, same as the phone page.

The database rules are the same ones the phone page follows
(`supabase/migrations/20261118*_gift_*.sql`). This screen only shows and asks.

## Parts

- Waveshare ESP32-S3-Touch-LCD-4.3 (the screen and the brains)
- PN532 card reader, **set to serial mode** (HSU: both DIP switches off)
- NTAG215 blank white cards
- Optional: the MonkMakes LED Arc (10 WS2812 LEDs) and a buzzer (pins in `include/config.h`)

## Wiring the card reader

The PN532 can't go on the board's I2C plug: it answers at address 0x24, the
same as the board's own CH422G chip (backlight and touch reset), and the two
would talk over each other. So it uses serial:

| PN532 | Screen board |
|-------|--------------|
| VCC   | 3.3 V (check the plug's voltage with a meter first) |
| GND   | GND |
| TX    | GPIO44 (RXD) |
| RX    | GPIO43 (TXD) |

GPIO43/44 also run to the USB-to-serial chip behind the USB-C port marked
UART. Power the station from the other USB-C port and leave the UART port
empty. **To check on the real board before soldering:** where 43/44 come out,
and that the native USB port powers the board on its own. If either is wrong,
change `READER_RX`/`READER_TX` in `include/config.h`.

## Flashing it

1. Install PlatformIO (`pip install platformio`).
2. Copy `include/secrets.example.h` to `include/secrets.h` and put in the
   club wifi. `secrets.h` is gitignored; never commit it (this repo is public).
3. Plug the board in by USB and run `pio run -t upload` in this folder.
4. On first start the screen asks a manager to sign the station in. Use the
   station's own staff login. The station keeps only a sign-in token, not the
   password. To end it, change that login's password.

## Testing on a spare card

`LOCK_CARDS` in `include/config.h` locks every card after writing it, so
nobody can change its link with a phone. Locking can't be undone. Set it to 0
only while trying things on a spare blank, and back to 1 before real cards.

## Checking the card writing without the hardware

`test/host/` runs the card code (`src/reader.cpp`) on a computer against a
pretend card: blank card found, link written, read back, locked, read as
ours, a locked card refused, someone else's card refused.

    g++ -std=c++17 -Itest/host -Iinclude -Isrc test/host/reader_test.cpp src/reader.cpp -o /tmp/reader_test && /tmp/reader_test
