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
- MonkMakes NeoPixel LED bar (10 LEDs), the footlight under the little man
- A USB-C plug with screw terminals (or a spare USB cable, cut), for the
  reader's two data wires
- No buzzer: the board has no pin left for one (see `include/config.h`)

## Wiring

**Worked out from Waveshare's schematic on Nov 23 2026 and not yet tried on
the real board.** Try it loose on the bench before anything goes in the box.

The screen board has two USB-C sockets on one edge. Power goes in the one
marked **UART**. The one marked **USB** carries the card reader's wires.

Why so roundabout: the reader can't go on the board's I2C plug (it answers at
address 0x24, the same as the board's own CH422G chip, which runs the
backlight and the touch reset), and the board's serial pins (GPIO43/44) only
go to the chip behind the UART socket, with nowhere to hook a wire. The two
data lines of the USB socket are GPIO19 and GPIO20, and the station doesn't
need them for USB, so the reader talks there.

| From | To |
|------|----|
| USB socket, D- (white wire in a USB cable), GPIO19 | reader TXD |
| USB socket, D+ (green wire), GPIO20 | reader RXD |
| USB socket, GND (black wire) | reader GND |
| USB socket, 5 V (red wire) | nothing: cap it or tape it off, it is live |
| Sensor plug, 3.3 V | reader VCC, and the LED bar's power |
| Sensor plug, GND | LED bar GND |
| Sensor plug, signal (GPIO6) | LED bar data in |

The reader gets 3.3 V, not 5 V, on purpose: its serial lines then stay at
3.3 V, which is all the screen board's pins take. The LED bar runs off the
same 3.3 V and is kept dim (`LED_BRIGHTNESS`) so it doesn't load the board.

If the reader isn't answering, the home screen says so and the station looks
for it again every ten seconds.

## Flashing it

1. Install PlatformIO (`pip install platformio`).
2. Copy `include/secrets.example.h` to `include/secrets.h` and put in the
   club wifi. `secrets.h` is gitignored; never commit it (this repo is public).
3. Plug the board's **UART** socket into the computer with a USB-C cable that
   carries data, and run `pio run -t upload` in this folder.
4. On first start the screen asks a manager to sign the station in. Use the
   station's own staff login. The station keeps only a sign-in token, not the
   password. To end it, change that login's password.

The sign-in screen has a line that says whether the wifi is connected and
whether the card reader is answering, so the wiring can be checked before the
station has a login. The same comes out of the UART socket as start-up
messages (115200 baud: `wifi: ...`, `reader: ...`, `station: ...`), never the
wifi name or password.

The picture is turned half way round (`SCREEN_TURNED` in `include/config.h`)
because that is how the screen sits in the Boulder: on the bench, stand the
board with its USB-C sockets on the left.

## Testing on a spare card

`LOCK_CARDS` in `include/config.h` locks every card after writing it, so
nobody can change its link with a phone. Locking can't be undone. Set it to 0
only while trying things on a spare blank, and back to 1 before real cards.

## Checking the card writing without the hardware

`test/host/` runs the card code (`src/reader.cpp`) on a computer against a
pretend card: blank card found, link written, read back, locked, read as
ours, a locked card refused, someone else's card refused.

    g++ -std=c++17 -Itest/host -Iinclude -Isrc test/host/reader_test.cpp src/reader.cpp -o /tmp/reader_test && /tmp/reader_test
