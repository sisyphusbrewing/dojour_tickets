// The screen board: backlight, screen, touch, and LVGL hooked up to them.
#pragma once
#include <lvgl.h>
void board_begin();        // call once in setup(); LVGL is ready after this
void board_backlight(bool on);
