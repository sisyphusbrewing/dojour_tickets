#include "feedback.h"
#include "config.h"
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>

#if LED_PIN >= 0
static Adafruit_NeoPixel strip(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);
#endif
enum Mode { IDLE, FLASH };
static Mode mode = IDLE;
static uint32_t flashColor = 0, flashUntil = 0;

static void beep(int hz, int ms) {
#if BUZZER_PIN >= 0
  tone(BUZZER_PIN, hz, ms);
  delay(ms + 10);
#endif
}

static void fill(uint32_t c) {
#if LED_PIN >= 0
  for (int i = 0; i < LED_COUNT; i++) strip.setPixelColor(i, c);
  strip.show();
#endif
}

void fx_begin() {
#if LED_PIN >= 0
  strip.begin();
  strip.setBrightness(LED_BRIGHTNESS);
#endif
  fill(0);
}
static void flash(uint32_t c, uint32_t ms) { mode = FLASH; flashColor = c; flashUntil = millis() + ms; fill(c); }
void fx_idle() { mode = IDLE; }
void fx_card() { flash(0x3060A0, 400); beep(2200, 40); }
void fx_ok() { flash(0x00C040, 1500); beep(1760, 70); beep(2350, 110); }
void fx_error() { flash(0xC00000, 1500); beep(330, 250); }

void fx_tick() {
#if LED_PIN >= 0
  static uint32_t last = 0;
  if (millis() - last < 30) return;
  last = millis();
  if (mode == FLASH) {
    if ((int32_t)(millis() - flashUntil) > 0) mode = IDLE;
    return;
  }
  // A slow slate-blue wave running along the footlight.
  float t = millis() / 1000.0f;
  for (int i = 0; i < LED_COUNT; i++) {
    float w = 0.5f + 0.5f * sinf(t * 1.4f + i * 6.283f / LED_COUNT);
    uint8_t b = 20 + 60 * w, g = 10 + 30 * w;
    strip.setPixelColor(i, strip.Color(g / 2, g, b));
  }
  strip.show();
#endif
}
