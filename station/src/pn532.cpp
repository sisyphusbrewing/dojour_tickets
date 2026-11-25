// See pn532.h. The frames, from NXP's PN532 user manual:
//   we send      00 00 FF <len> <-len> D4 <command...> <checksum> 00
//   it says      00 00 FF 00 FF 00                        "got it" (ACK)
//   then         00 00 FF <len> <-len> D5 <command+1> <answer...> <checksum> 00
// <len> counts D4/D5 and everything after it up to the checksum; the checksum
// makes those bytes add up to 0.
#include "pn532.h"
#include "config.h"

static PnCounts counts;
const PnCounts &pn_counts() { return counts; }
static PnLast last;
const PnLast &pn_last() { return last; }

static const uint8_t ACK[6] = {0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00};

static void empty_inbox() {
  while (Serial1.available()) Serial1.read();
}

// The next byte from the reader, or -1 if none comes within `ms`.
static int next_byte(uint16_t ms) {
  uint32_t t0 = millis();
  while (!Serial1.available()) {
    if ((uint32_t)(millis() - t0) > ms) return -1;
    delay(1);
  }
  return Serial1.read();
}

// Read one whole frame. Gives back:
//   -1  nothing came in time        -2  something came but it was garbled
//    0  an ACK                      >0  that many bytes put in buf (D5, command+1, answer...)
static int read_frame(uint8_t *buf, uint8_t cap, uint16_t firstMs) {
  int b = next_byte(firstMs);
  if (b < 0) return -1;
  int prev = -1;
  for (int skipped = 0; !(prev == 0x00 && b == 0xFF); skipped++) {   // every frame starts 00 FF
    if (skipped > 40) return -2;
    prev = b;
    b = next_byte(20);
    if (b < 0) return -2;
  }
  int len = next_byte(20), lcs = next_byte(20);
  if (len < 0 || lcs < 0) return -2;
  if (len == 0x00 && lcs == 0xFF) { next_byte(20); return 0; }       // ACK, and its closing 00
  if (((len + lcs) & 0xFF) != 0 || len == 0 || len > cap) return -2;
  uint8_t sum = 0;
  for (int i = 0; i < len; i++) {
    int d = next_byte(20);
    if (d < 0) return -2;
    buf[i] = (uint8_t)d;
    sum += (uint8_t)d;
  }
  int dcs = next_byte(20);
  next_byte(20);                                                      // closing 00
  if (dcs < 0 || ((sum + dcs) & 0xFF) != 0) return -2;
  return len;
}

// Send one command and wait up to waitMs for its answer. Gives back how many
// answer bytes were put in out (after "D5 command+1"), or -1 for no proper
// answer.
static int ask(const uint8_t *cmd, uint8_t n, uint8_t *out, uint8_t cap, uint16_t waitMs) {
  empty_inbox();                       // nothing old may be mistaken for this answer
  uint8_t f[48];
  if (n + 8 > (int)sizeof f) return -1;
  size_t k = 0;
  uint8_t len = n + 1, sum = 0xD4;
  f[k++] = 0x00; f[k++] = 0x00; f[k++] = 0xFF;
  f[k++] = len;  f[k++] = (uint8_t)(0x100 - len);
  f[k++] = 0xD4;
  for (uint8_t i = 0; i < n; i++) { f[k++] = cmd[i]; sum += cmd[i]; }
  f[k++] = (uint8_t)(0x100 - sum);
  f[k++] = 0x00;
  Serial1.write(f, k);
  counts.sent++;

  uint8_t buf[64];
  if (read_frame(buf, sizeof buf, 60) != 0) return -1;      // it didn't say "got it"
  counts.acked++;
  int r = read_frame(buf, sizeof buf, waitMs);
  if (r == -1) {                       // still working on it (looking for a card): tell it to stop
    Serial1.write(ACK, sizeof ACK);
    delay(3);
    empty_inbox();
    return -1;
  }
  if (r < 2 || buf[0] != 0xD5 || buf[1] != (uint8_t)(cmd[0] + 1)) return -1;
  counts.answered++;
  int m = r - 2;
  if (m > cap) m = cap;
  memcpy(out, buf + 2, m);
  return m;
}

bool pn_begin() {
  Serial1.begin(115200, SERIAL_8N1, READER_RX, READER_TX);
  // A long run of wake-up bytes: after power-up the reader sleeps until it sees them.
  uint8_t wake[16] = {0x55, 0x55};
  Serial1.write(wake, sizeof wake);
  delay(5);
  uint8_t out[8];
  const uint8_t sam[] = {0x14, 0x01, 0x14, 0x01};          // normal mode (no security chip fitted)
  if (ask(sam, sizeof sam, out, sizeof out, 100) < 0) {     // the first one after waking may be missed
    delay(20);
    if (ask(sam, sizeof sam, out, sizeof out, 100) < 0) return false;
  }
  const uint8_t ver[] = {0x02};                             // "which chip are you": a PN532 says 32 ...
  if (ask(ver, sizeof ver, out, sizeof out, 100) < 4 || out[0] != 0x32) return false;
  // Look for a card a few times per question, then answer "none", instead of
  // looking for ever: each question gets its answer and nothing is left hanging.
  const uint8_t tries[] = {0x32, 0x05, 0xFF, 0x01, 0x03};
  ask(tries, sizeof tries, out, sizeof out, 100);
  return true;
}

bool pn_find(uint8_t uid[7], uint8_t &len) {
  const uint8_t cmd[] = {0x4A, 0x01, 0x00};                 // one card, the usual kind (ISO 14443 A)
  uint8_t out[24];
  int m = ask(cmd, sizeof cmd, out, sizeof out, 150);
  // answer: how many, then for the first: number, 2 + 1 bytes of card type, id length, id
  if (m < 6 || out[0] != 1) return false;
  len = out[5] > 7 ? 7 : out[5];
  if (m < 6 + len) return false;
  memcpy(uid, out + 6, len);
  last.type[0] = out[2]; last.type[1] = out[3]; last.kind = out[4]; last.idLen = out[5];
  counts.cards++;
  return true;
}

// A page didn't go through: count it and keep the reader's reason.
static bool refused(int m, const uint8_t *out) {
  counts.refused++;
  last.why = m >= 1 ? out[0] : -1;
  return false;
}

bool pn_read(uint8_t page, uint8_t out4[4]) {
  const uint8_t cmd[] = {0x40, 0x01, 0x30, page};           // to card 1: READ from this page (16 bytes come back)
  uint8_t out[20];
  counts.pages++;
  int m = ask(cmd, sizeof cmd, out, sizeof out, 120);
  if (m < 5 || out[0] != 0x00) return refused(m, out);      // first byte 00 = the card answered
  memcpy(out4, out + 1, 4);
  return true;
}

bool pn_write(uint8_t page, const uint8_t in[4]) {
  const uint8_t cmd[] = {0x40, 0x01, 0xA2, page, in[0], in[1], in[2], in[3]};   // to card 1: WRITE this page
  uint8_t out[4];
  counts.pages++;
  int m = ask(cmd, sizeof cmd, out, sizeof out, 120);
  if (m < 1 || out[0] != 0x00) return refused(m, out);
  return true;
}
