// Drives the Waveshare 4.3" board directly with the ESP32's own screen driver
// (esp_lcd), so the station doesn't depend on Waveshare's libraries and their
// version changes. Three parts:
//   CH422G  a small helper chip on I2C that switches the backlight and resets
//           the touch chip. It takes plain one-byte writes at fixed addresses.
//   GT911   the touch chip, also on I2C. We ask it where the finger is.
//   RGB LCD the screen itself, fed from a picture kept in PSRAM.
#include "board.h"
#include "config.h"
#include <Arduino.h>
#include <Wire.h>
#include <esp_heap_caps.h>
#include <esp_lcd_panel_ops.h>
#include <esp_lcd_panel_rgb.h>

static esp_lcd_panel_handle_t panel = nullptr;
static uint8_t exio = EXIO_SD_CS;   // what the CH422G outputs are set to

// ---- CH422G ----
static void ch422_write(uint8_t addr, uint8_t v) {
  Wire.beginTransmission(addr);
  Wire.write(v);
  Wire.endTransmission();
}
static void exio_set(uint8_t bit, bool on) {
  exio = on ? (exio | bit) : (exio & ~bit);
  ch422_write(0x38, exio);           // 0x38: set IO0-IO7
}

void board_backlight(bool on) { exio_set(EXIO_BACKLIGHT, on); }

// ---- GT911 touch ----
static void gt911_reset() {
  // Holding the IRQ pin low while the reset is let go picks address 0x5D.
  pinMode(TOUCH_IRQ, OUTPUT);
  digitalWrite(TOUCH_IRQ, LOW);
  exio_set(EXIO_TP_RST, false);
  delay(20);
  exio_set(EXIO_TP_RST, true);
  delay(60);
  pinMode(TOUCH_IRQ, INPUT);
  delay(50);
}

static bool gt911_read(uint16_t reg, uint8_t *buf, size_t n) {
  Wire.beginTransmission(GT911_ADDR);
  Wire.write(reg >> 8);
  Wire.write(reg & 0xFF);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)GT911_ADDR, (int)n) != (int)n) return false;
  for (size_t i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}
static void gt911_write8(uint16_t reg, uint8_t v) {
  Wire.beginTransmission(GT911_ADDR);
  Wire.write(reg >> 8);
  Wire.write(reg & 0xFF);
  Wire.write(v);
  Wire.endTransmission();
}

static void touch_read(lv_indev_drv_t *, lv_indev_data_t *data) {
  static int16_t lx = 0, ly = 0;
  uint8_t st = 0;
  data->state = LV_INDEV_STATE_REL;
  if (gt911_read(0x814E, &st, 1) && (st & 0x80)) {
    if ((st & 0x0F) > 0) {
      uint8_t p[6];
      if (gt911_read(0x8150, p, 6)) {
        lx = p[0] | (p[1] << 8);
        ly = p[2] | (p[3] << 8);
        data->state = LV_INDEV_STATE_PR;
      }
    }
    gt911_write8(0x814E, 0);   // tell the chip we read it
  }
  data->point.x = lx;
  data->point.y = ly;
}

// ---- Screen ----
static void flush(lv_disp_drv_t *drv, const lv_area_t *a, lv_color_t *px) {
  esp_lcd_panel_draw_bitmap(panel, a->x1, a->y1, a->x2 + 1, a->y2 + 1, px);
  lv_disp_flush_ready(drv);
}

static void lcd_begin() {
  const int pins[16] = LCD_DATA_PINS;
  esp_lcd_rgb_panel_config_t cfg = {};
  cfg.clk_src = LCD_CLK_SRC_DEFAULT;
  cfg.timings.pclk_hz = LCD_PCLK_HZ;
  cfg.timings.h_res = LCD_W;
  cfg.timings.v_res = LCD_H;
  cfg.timings.hsync_pulse_width = LCD_HSYNC_PULSE;
  cfg.timings.hsync_back_porch = LCD_HSYNC_BACK;
  cfg.timings.hsync_front_porch = LCD_HSYNC_FRONT;
  cfg.timings.vsync_pulse_width = LCD_VSYNC_PULSE;
  cfg.timings.vsync_back_porch = LCD_VSYNC_BACK;
  cfg.timings.vsync_front_porch = LCD_VSYNC_FRONT;
  cfg.timings.flags.pclk_active_neg = 1;
  cfg.data_width = 16;
  cfg.num_fbs = 1;
  // A small buffer in fast memory keeps the picture steady while wifi is busy.
  cfg.bounce_buffer_size_px = LCD_W * 10;
  cfg.hsync_gpio_num = LCD_PIN_HSYNC;
  cfg.vsync_gpio_num = LCD_PIN_VSYNC;
  cfg.de_gpio_num = LCD_PIN_DE;
  cfg.pclk_gpio_num = LCD_PIN_PCLK;
  cfg.disp_gpio_num = -1;
  for (int i = 0; i < 16; i++) cfg.data_gpio_nums[i] = pins[i];
  cfg.flags.fb_in_psram = 1;
  ESP_ERROR_CHECK(esp_lcd_new_rgb_panel(&cfg, &panel));
  ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
  ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
}

void board_begin() {
  Wire.begin(I2C_SDA, I2C_SCL, 400000);
  ch422_write(0x24, 0x01);           // 0x24: IO0-IO7 are outputs
  ch422_write(0x38, exio);
  gt911_reset();
  lcd_begin();
  board_backlight(true);

  lv_init();
  static lv_disp_draw_buf_t draw;
  const size_t lines = 80;
  lv_color_t *b1 = (lv_color_t *)heap_caps_malloc(LCD_W * lines * sizeof(lv_color_t), MALLOC_CAP_SPIRAM);
  lv_color_t *b2 = (lv_color_t *)heap_caps_malloc(LCD_W * lines * sizeof(lv_color_t), MALLOC_CAP_SPIRAM);
  lv_disp_draw_buf_init(&draw, b1, b2, LCD_W * lines);

  static lv_disp_drv_t disp;
  lv_disp_drv_init(&disp);
  disp.hor_res = LCD_W;
  disp.ver_res = LCD_H;
  disp.flush_cb = flush;
  disp.draw_buf = &draw;
  lv_disp_drv_register(&disp);

  static lv_indev_drv_t touch;
  lv_indev_drv_init(&touch);
  touch.type = LV_INDEV_TYPE_POINTER;
  touch.read_cb = touch_read;
  lv_indev_drv_register(&touch);
}
