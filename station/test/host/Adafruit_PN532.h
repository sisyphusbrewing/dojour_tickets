#pragma once
#include "Arduino.h"
#define PN532_MIFARE_ISO14443A 0
extern uint8_t mem[135][4];
struct Adafruit_PN532 {
  Adafruit_PN532(int, HardwareSerial*){}
  void begin(){} uint32_t getFirmwareVersion(){return 1;} void SAMConfig(){}
  bool readPassiveTargetID(int, uint8_t*u, uint8_t*l, int){ u[0]=4;u[1]=1;*l=7; return true; }
  bool ntag2xx_ReadPage(uint8_t p, uint8_t*o){ memcpy(o,mem[p],4); return true; }
  bool ntag2xx_WritePage(uint8_t p, uint8_t*d){ if(p==2){mem[2][2]|=d[2];mem[2][3]|=d[3];return true;} if(p==3){for(int i=0;i<4;i++)mem[3][i]|=d[i];return true;} memcpy(mem[p],d,4); return true; }
};
