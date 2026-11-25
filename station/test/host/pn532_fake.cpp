// A pretend reader with a pretend card on it, for reader_test.cpp: the card's
// pages live in mem, and locking works the way a real NTAG215 does (lock
// bits can be set but never cleared). It can also behave like a card on a
// weak signal: with fake_drop_every = N, every Nth page fails and the card
// "lets go", so every page after it fails too until the card is found again.
#include "pn532.h"
uint8_t mem[135][4];
int fake_drop_every = 0, fake_drops = 0;
uint8_t fake_id = 1;                      // change it to swap in a different card
static bool held = true;
static int ops = 0;
static PnCounts c;
static PnLast l = {{0x00, 0x44}, 0x00, 7, 0};
const PnCounts &pn_counts() { return c; }
const PnLast &pn_last() { return l; }
bool pn_begin() { return true; }
bool pn_find(uint8_t uid[7], uint8_t &len) { memset(uid, 0, 7); uid[0]=4; uid[1]=fake_id; len=7; held=true; c.cards++; return true; }
static bool ok() {
  c.pages++;
  if (held && fake_drop_every && ++ops % fake_drop_every == 0) { held = false; fake_drops++; }
  if (!held) { c.refused++; l.why = 0x01; }
  return held;
}
bool pn_read(uint8_t p, uint8_t out[4]) { if (!ok()) return false; memcpy(out, mem[p], 4); return true; }
bool pn_write(uint8_t p, const uint8_t d[4]) {
  if (!ok()) return false;
  if (p==2) { mem[2][2]|=d[2]; mem[2][3]|=d[3]; return true; }
  if (p==3) { for (int i=0;i<4;i++) mem[3][i]|=d[i]; return true; }
  memcpy(mem[p], d, 4); return true;
}
