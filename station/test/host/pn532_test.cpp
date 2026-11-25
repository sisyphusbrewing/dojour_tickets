// Checks src/pn532.cpp (how the station talks to the card reader) against a
// pretend PN532 that answers the way the real chip does, including the
// awkward cases: old bytes left in the line, an answer that never comes, a
// garbled answer, extra zeros before a frame.
#include "pn532.h"
#include <cassert>
HardwareSerial Serial1;

static bool card = true, alive = true, silentFind = false, garbleNext = false, extraZeros = false;
static uint8_t mem[135][4];
static int aborts = 0, badFrames = 0;

static void reply(HardwareSerial &s, std::vector<uint8_t> d) {
  std::vector<uint8_t> f = {0x00, 0x00, 0xFF, (uint8_t)d.size(), (uint8_t)(0x100 - d.size())};
  uint8_t sum = 0;
  for (auto b : d) { f.push_back(b); sum += b; }
  f.push_back((uint8_t)(0x100 - sum)); f.push_back(0x00);
  if (garbleNext) { f[7] ^= 0x40; garbleNext = false; }
  if (extraZeros) for (int i = 0; i < 3; i++) s.rx.push_back(0x00);
  for (auto b : f) s.rx.push_back(b);
}

static void pn532(HardwareSerial &s, const uint8_t *b, size_t n) {
  static const uint8_t ACK[6] = {0, 0, 0xFF, 0, 0xFF, 0};
  if (n == 6 && !memcmp(b, ACK, 6)) { aborts++; return; }
  if (b[0] == 0x55) return;                               // wake-up bytes
  if (!alive) return;
  // a command frame: check it the way the chip would
  uint8_t len = b[3], sum = 0;
  if (n != (size_t)len + 7 || b[0] || b[1] || b[2] != 0xFF || ((len + b[4]) & 0xFF) || b[5] != 0xD4) { badFrames++; return; }
  for (int i = 0; i < len; i++) sum += b[5 + i];
  if (((sum + b[5 + len]) & 0xFF) || b[6 + len] != 0x00) { badFrames++; return; }
  for (auto a : ACK) s.rx.push_back(a);
  const uint8_t *c = b + 6;
  switch (c[0]) {
    case 0x14: reply(s, {0xD5, 0x15}); break;
    case 0x02: reply(s, {0xD5, 0x03, 0x32, 0x01, 0x06, 0x07}); break;
    case 0x32: reply(s, {0xD5, 0x33}); break;
    case 0x4A:
      if (silentFind) break;                              // still looking: no answer yet
      if (card) reply(s, {0xD5, 0x4B, 0x01, 0x01, 0x00, 0x44, 0x00, 0x07, 0x04, 0xA1, 0xB2, 0xC3, 0xD4, 0xE5, 0xF6});
      else reply(s, {0xD5, 0x4B, 0x00});
      break;
    case 0x40:
      if (!card) { reply(s, {0xD5, 0x41, 0x01}); break; }
      if (c[2] == 0x30) {
        std::vector<uint8_t> d = {0xD5, 0x41, 0x00};
        for (int p = c[3]; p < c[3] + 4; p++) for (int i = 0; i < 4; i++) d.push_back(mem[p % 135][i]);
        reply(s, d);
      } else if (c[2] == 0xA2) { memcpy(mem[c[3]], c + 4, 4); reply(s, {0xD5, 0x41, 0x00}); }
      break;
    default: reply(s, {0x7F});                            // the chip's "I don't know that" frame
  }
}

int main() {
  fake_step() = 1;
  Serial1.on_write = pn532;
  uint8_t cc[4] = {0xE1, 0x10, 0x3E, 0x00}; memcpy(mem[3], cc, 4);

  assert(pn_begin());
  uint8_t uid[7], len = 0, got[4];

  // a card, with rubbish already sitting in the line from before
  for (uint8_t junk : {0x13, 0x00, 0xFF, 0x00, 0x00}) Serial1.rx.push_back(junk);
  assert(pn_find(uid, len) && len == 7 && uid[0] == 0x04 && uid[6] == 0xF6);
  assert(pn_last().type[0] == 0x00 && pn_last().type[1] == 0x44 && pn_last().kind == 0x00 && pn_last().idLen == 7);

  // its pages: read, write, read back
  assert(pn_read(3, got) && !memcmp(got, cc, 4));
  const uint8_t w[4] = {1, 2, 3, 4};
  assert(pn_write(4, w) && pn_read(4, got) && !memcmp(got, w, 4));

  // a garbled answer is refused, and the next question is fine again
  garbleNext = true;
  assert(!pn_read(3, got));
  assert(pn_read(3, got) && !memcmp(got, cc, 4));

  // some chips send extra zeros before a frame
  extraZeros = true;
  assert(pn_find(uid, len) && pn_read(4, got) && !memcmp(got, w, 4));
  extraZeros = false;

  // no card: a clean "none"; and a card that has gone: read and write both say no
  card = false;
  uint32_t refusedBefore = pn_counts().refused;
  assert(!pn_find(uid, len) && !pn_read(3, got) && !pn_write(4, w));
  assert(pn_counts().refused == refusedBefore + 2 && pn_last().why == 0x01);   // and the reader's reason is kept

  // the chip still looking when we give up: we tell it to stop, and the next question works
  silentFind = true; int before = aborts;
  assert(!pn_find(uid, len) && aborts == before + 1);
  silentFind = false; card = true;
  assert(pn_find(uid, len));

  // a reader that isn't there
  uint32_t ackedBefore = pn_counts().acked;
  alive = false;
  assert(!pn_find(uid, len) && !pn_begin() && pn_counts().acked == ackedBefore);
  alive = true;
  assert(pn_begin());

  assert(badFrames == 0);
  printf("asked %u, acknowledged %u, answered %u, cards %u\n", (unsigned)pn_counts().sent, (unsigned)pn_counts().acked,
         (unsigned)pn_counts().answered, (unsigned)pn_counts().cards);
  puts("reader link: all good");
}
