// A pretend reader with a pretend card on it, for reader_test.cpp: the card's
// pages live in mem, and locking works the way a real NTAG215 does (lock
// bits can be set but never cleared).
#include "pn532.h"
uint8_t mem[135][4];
static PnCounts c;
const PnCounts &pn_counts() { return c; }
bool pn_begin() { return true; }
bool pn_find(uint8_t uid[7], uint8_t &len) { uid[0]=4; uid[1]=1; len=7; return true; }
bool pn_read(uint8_t p, uint8_t out[4]) { memcpy(out, mem[p], 4); return true; }
bool pn_write(uint8_t p, const uint8_t d[4]) {
  if (p==2) { mem[2][2]|=d[2]; mem[2][3]|=d[3]; return true; }
  if (p==3) { for (int i=0;i<4;i++) mem[3][i]|=d[i]; return true; }
  memcpy(mem[p], d, 4); return true;
}
