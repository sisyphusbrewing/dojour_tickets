// LVGL 8.4 settings for the Boulder. Only what differs from LVGL's defaults.
#ifndef LV_CONF_H
#define LV_CONF_H
#define LV_CONF_INCLUDE_SIMPLE 1
#if 1
#define LV_COLOR_DEPTH 16
#define LV_COLOR_16_SWAP 0
#define LV_MEM_CUSTOM 1               // use the board's PSRAM through malloc
#define LV_MEM_CUSTOM_INCLUDE <stdlib.h>
#define LV_MEM_CUSTOM_ALLOC malloc
#define LV_MEM_CUSTOM_FREE free
#define LV_MEM_CUSTOM_REALLOC realloc
#define LV_TICK_CUSTOM 1
#define LV_TICK_CUSTOM_INCLUDE "Arduino.h"
#define LV_TICK_CUSTOM_SYS_TIME_EXPR (millis())
#define LV_DISP_DEF_REFR_PERIOD 20
#define LV_INDEV_DEF_READ_PERIOD 20
#define LV_USE_LOG 0
#define LV_FONT_MONTSERRAT_16 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_28 1
#define LV_FONT_MONTSERRAT_36 1
#define LV_FONT_MONTSERRAT_48 1
#define LV_FONT_DEFAULT &lv_font_montserrat_20
#define LV_USE_KEYBOARD 1
#define LV_USE_TEXTAREA 1
#define LV_USE_BTNMATRIX 1
#define LV_THEME_DEFAULT_DARK 1
#endif
#endif
