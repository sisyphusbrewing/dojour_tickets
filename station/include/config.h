// The Boulder's wiring and settings, in one place.
//
// Screen board: Waveshare ESP32-S3-Touch-LCD-4.3. Pin numbers below are from
// Waveshare's wiki and schematic (read Nov 18 2026).
//
// THE CARD READER IS NOT ON THE I2C PLUG. The PN532 answers I2C address 0x24,
// and so does the board's own CH422G chip (it runs the backlight and the touch
// reset), so they can't share the I2C plug. The PN532 is wired in serial mode
// instead (its two DIP switches: HSU, both off). Which pins: see READER_RX/TX.
// Check them on the real board before soldering; see README.md.
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
// card select (kept high = off), bit 5 USB select (low = USB to the ESP32).
#define EXIO_TP_RST (1 << 1)
#define EXIO_BACKLIGHT (1 << 2)
#define EXIO_SD_CS (1 << 4)

// ---- Card reader (PN532, serial mode) ----
// GPIO43/44 are the board's UART pins. They also run to the USB-to-serial
// chip on the "UART" USB-C port, so power the station from the OTHER USB-C
// port (marked USB) and leave the UART port empty. To be confirmed on the
// real board.
#define READER_RX 44   // ESP32 receives here: wire to the PN532's TX
#define READER_TX 43   // wire to the PN532's RX
#define READER_RESET -1

// ---- Lights and buzzer (not wired yet: -1 means none) ----
#define LED_PIN -1          // a strip of WS2812 LEDs around the boulder
#define LED_COUNT 24
#define BUZZER_PIN -1       // a passive buzzer
