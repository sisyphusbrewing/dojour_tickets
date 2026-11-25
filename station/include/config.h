// The Boulder's wiring and settings, in one place.
//
// Screen board: Waveshare ESP32-S3-Touch-LCD-4.3. Pin numbers below are from
// Waveshare's wiki and schematic (read Nov 18 and Nov 23 2026).
//
// THE CARD READER IS NOT ON THE I2C PLUG. The PN532 answers I2C address 0x24,
// and so does the board's own CH422G chip (it runs the backlight and the touch
// reset), so they can't share the I2C plug. The PN532 is wired in serial mode
// instead (its two DIP switches: HSU, both off). Which pins: see READER_RX/TX.
// The wiring is drawn out in README.md.
#pragma once

// ---- Supabase (the same database the staff site uses) ----
// The URL and the anon key are public (they are in staff.js too); the rules
// that matter live in the database.
#define SUPABASE_URL "https://idsdwkubqnavkazlteis.supabase.co"
#define SUPABASE_ANON_KEY "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ"
#define LOGIN_DOMAIN "sisyphusbrewing.com"   // "rjoseph" signs in as rjoseph@...

// What gets written on every new card. The phone opens this when tapped.
#define CARD_LINK_HOST "staff.sisyphusbrewing.com/gift/?c="   // after "https://"

// Lock each card after writing it, so nobody can rewrite the link with a
// phone. Locking can't be undone. Leave this on for real cards; turn it off
// only while testing on a spare blank.
#define LOCK_CARDS 1

// Quick amounts on the number pad, in dollars.
#define QUICK_AMOUNTS {25, 50, 100}

// After this long with nobody touching it, a card's screen goes back home.
#define IDLE_BACK_MS 45000UL

// ---- Screen (800x480 RGB) ----
#define LCD_W 800
#define LCD_H 480
#define LCD_PCLK_HZ (16 * 1000 * 1000)
#define LCD_PIN_DE 5
#define LCD_PIN_VSYNC 3
#define LCD_PIN_HSYNC 46
#define LCD_PIN_PCLK 7
// 16 data lines, blue first: B3..B7, G2..G7, R3..R7
#define LCD_DATA_PINS {14, 38, 18, 17, 10,  39, 0, 45, 48, 47, 21,  1, 2, 42, 41, 40}
#define LCD_HSYNC_PULSE 4
#define LCD_HSYNC_BACK 8
#define LCD_HSYNC_FRONT 8
#define LCD_VSYNC_PULSE 4
#define LCD_VSYNC_BACK 8
#define LCD_VSYNC_FRONT 8

// ---- Touch (GT911) and the CH422G helper chip share this I2C bus ----
#define I2C_SDA 8
#define I2C_SCL 9
#define TOUCH_IRQ 4
#define GT911_ADDR 0x5D

// CH422G outputs (EXIO pins): bit 1 touch reset, bit 2 backlight, bit 4 SD
// card select (kept high = off), bit 5 says where the USB socket's two data
// lines go: low = to GPIO19/20 (what the card reader needs), high = to the
// board's CAN chip. We never set bit 5, so it stays low.
#define EXIO_TP_RST (1 << 1)
#define EXIO_BACKLIGHT (1 << 2)
#define EXIO_SD_CS (1 << 4)

// The Boulder holds the screen turned half way round, so both USB-C sockets
// face the roomy inside of the hill. 1 turns the picture and the touch back
// the right way up. 0 is for a board lying on the bench with its sockets on
// the right.
#define SCREEN_TURNED 1

// ---- Card reader (PN532, serial mode) ----
// This board has no plain serial pins. GPIO43/44 run only to the
// USB-to-serial chip behind the USB-C socket marked UART, with nowhere to
// hook a wire. So the reader talks on GPIO19/20 instead: the two data lines
// of the OTHER USB-C socket (marked USB), reached with a USB-C plug that has
// screw terminals, or a cut USB cable (white is D-, green is D+). The station
// is powered through the UART socket. Worked out from Waveshare's schematic
// on Nov 23 2026; first tried on the real board when Sam wires it.
#define READER_RX 19   // USB D- (white): the ESP32 listens here. Wire to the PN532's TX
#define READER_TX 20   // USB D+ (green): wire to the PN532's RX
#define READER_RESET -1

// ---- Lights and buzzer (-1 means none) ----
// The LED bar is the footlight in the road under the little man. Its data
// wire goes to GPIO6, the signal pin of the board's 3-pin "Sensor" plug.
#define LED_PIN 6
#define LED_COUNT 10          // MonkMakes NeoPixel LED bar
#define LED_BRIGHTNESS 60     // out of 255. Low on purpose: the bar runs off the board's own supply
// No pin is left for the buzzer once the reader and the lights are on. The
// lights do the telling.
#define BUZZER_PIN -1
