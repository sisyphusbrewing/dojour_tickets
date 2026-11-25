// How a card is laid out (NTAG215, 4-byte pages):
//   page 2, bytes 2-3   static lock bits (lock pages 3-15)
//   page 3              capability container: E1 10 3E 00 on a blank card.
//                       The last byte becomes 0F when the card is locked.
//   page 4 on           the NDEF message: 03 <length> <record> FE
//   page 130 (0x82)     dynamic lock bits (lock pages 16 and up)
// The record is one URL: D1 01 <len> 'U' 04 "staff.sisyphusbrewing.com/gift/?c=<code>"
// (04 means "https://"). That is what NFC Tools writes too, so a card made
// here and a card made by hand read the same.
#include "reader.h"
#include "config.h"
#include "pn532.h"

static uint8_t lastUid[7];
static uint8_t lastLen = 0;
static uint32_t lastSeen = 0;

bool reader_begin() { return pn_begin(); }

// Has the reader gone quiet since the last time this was asked? True when
// questions went out and not one was acknowledged (a wire came loose).
bool reader_went_quiet() {
  static uint32_t sent = 0, acked = 0;
  const PnCounts &c = pn_counts();
  bool quiet = c.sent - sent >= 5 && c.acked == acked;
  sent = c.sent;
  acked = c.acked;
  return quiet;
}

String reader_report() {
  const PnCounts &c = pn_counts();
  char b[160];
  snprintf(b, sizeof b, "reader: %lu asked, %lu acknowledged, %lu answered, %lu pages, %lu refused, %lu cards seen",
           (unsigned long)c.sent, (unsigned long)c.acked, (unsigned long)c.answered,
           (unsigned long)c.pages, (unsigned long)c.refused, (unsigned long)c.cards);
  return b;
}

// Why the last card was sorted the way it was, for the start-up messages:
// the kind of chip and where reading stopped. Never what is on the card.
static char why[96];
String reader_card_note() {
  const PnLast &l = pn_last();
  char b[160];
  snprintf(b, sizeof b, "chip %02X%02X/%02X, %u-byte id%s%s", l.type[0], l.type[1], l.kind, l.idLen, why[0] ? "; " : "", why);
  return b;
}

// After a page fails the card has usually let go of the conversation (it was
// nudged, or the signal dipped), and asking again gets nothing until the
// reader finds it afresh. So: find it again, make sure it is the same card,
// then ask again. A different card in its place stops the job at once.
static bool same_card_again() {
  uint8_t uid[7], len = 0;
  for (int tries = 0; tries < 3; tries++)
    if (pn_find(uid, len)) return len == lastLen && memcmp(uid, lastUid, len) == 0;
  return true;   // not found this time: let the next try at the page decide
}
static bool read_page(uint8_t page, uint8_t out[4]) {
  for (int tries = 0; tries < 4; tries++) {
    if (pn_read(page, out)) return true;
    if (!same_card_again()) return false;
  }
  return false;
}
static bool write_page(uint8_t page, const uint8_t in[4]) {
  for (int tries = 0; tries < 4; tries++) {
    if (pn_write(page, in)) return true;
    if (!same_card_again()) return false;
  }
  return false;
}

// Read the card's NDEF bytes (from page 4) and sort it.
static void classify(Tag &t) {
  t.kind = TAG_OTHER;
  t.code[0] = 0;
  why[0] = 0;
  uint8_t cc[4];
  if (!read_page(3, cc)) { snprintf(why, sizeof why, "couldn't read it (reader code %02X)", pn_last().why & 0xFF); return; }
  bool unformatted = !cc[0] && !cc[1] && !cc[2] && !cc[3];
  if (!unformatted && (cc[0] != 0xE1 || cc[2] < 0x3E)) {   // not NDEF, or too small
    snprintf(why, sizeof why, "not the kind of card ours are (its label page says %02X %02X %02X %02X)", cc[0], cc[1], cc[2], cc[3]);
    return;
  }
  bool writable = unformatted || cc[3] == 0x00;

  uint8_t buf[120];
  for (int p = 0; p < 30; p++)
    if (!read_page(4 + p, buf + p * 4)) {
      snprintf(why, sizeof why, "reading stopped at page %d (reader code %02X)", 4 + p, pn_last().why & 0xFF);
      return;
    }
  snprintf(why, sizeof why, "it holds something that isn't our link");

  size_t i = 0;
  while (i < sizeof buf && (buf[i] == 0x01 || buf[i] == 0x02)) i += 2 + buf[i + 1];   // lock/memory TLVs
  if (i >= sizeof buf) return;
  if (buf[i] == 0x00 || buf[i] == 0xFE || (buf[i] == 0x03 && buf[i + 1] == 0x00)) {
    if (writable) { t.kind = TAG_BLANK; why[0] = 0; }
    else snprintf(why, sizeof why, "empty, but locked");
    return;
  }
  if (buf[i] != 0x03) return;
  size_t len = buf[i + 1], r = i + 2;
  if (len == 0xFF || r + len > sizeof buf) return;

  uint8_t hdr = buf[r], typeLen = buf[r + 1];
  if (!(hdr & 0x10)) return;                           // only short records
  size_t payLen = buf[r + 2];
  size_t idLen = (hdr & 0x08) ? buf[r + 3] : 0;
  size_t ty = r + 3 + ((hdr & 0x08) ? 1 : 0);
  size_t pay = ty + typeLen + idLen;
  if (typeLen != 1 || buf[ty] != 'U' || pay + payLen > sizeof buf) return;

  // Find the code after ".../gift/?c=". Cards written by hand with NFC Tools
  // may spell the start differently (http, www), so look for the end part.
  String url;
  for (size_t k = 1; k < payLen; k++) url += (char)buf[pay + k];
  url.toLowerCase();
  int at = url.indexOf("sisyphusbrewing.com/gift/?c=");
  if (at < 0) return;
  at += strlen("sisyphusbrewing.com/gift/?c=");
  if ((int)url.length() < at + 32) return;
  for (int k = 0; k < 32; k++) {
    char c = url[at + k];
    if (!isxdigit((unsigned char)c)) return;
    t.code[k] = c;
  }
  t.code[32] = 0;
  t.kind = TAG_OURS;
  why[0] = 0;
}

bool reader_poll(Tag &t) {
  uint8_t uid[7], len = 0;
  if (!pn_find(uid, len)) return false;
  bool same = len == lastLen && memcmp(uid, lastUid, len) == 0;
  bool fresh = !same || millis() - lastSeen > 1500;   // the same card, lifted and set down again
  lastSeen = millis();
  if (!fresh) return false;
  memcpy(lastUid, uid, len);
  lastLen = len;
  memcpy(t.uid, uid, len);
  t.uidLen = len;
  classify(t);
  return true;
}

bool reader_still_there() {
  uint8_t uid[7], len = 0;
  if (!pn_find(uid, len)) return millis() - lastSeen < 1500;
  if (len == lastLen && memcmp(uid, lastUid, len) == 0) lastSeen = millis();
  return millis() - lastSeen < 1500;
}

bool reader_write(const char *code, String &err) {
  // Build the message.
  uint8_t msg[128];
  const size_t hostLen = strlen(CARD_LINK_HOST);
  const uint8_t payLen = 1 + hostLen + 32;
  size_t n = 0;
  msg[n++] = 0x03;
  msg[n++] = 4 + payLen;          // record = 4 header bytes + payload
  msg[n++] = 0xD1;                // one short, well-known record
  msg[n++] = 0x01;                // type is 1 byte
  msg[n++] = payLen;
  msg[n++] = 'U';
  msg[n++] = 0x04;                // "https://"
  memcpy(msg + n, CARD_LINK_HOST, hostLen); n += hostLen;
  memcpy(msg + n, code, 32); n += 32;
  msg[n++] = 0xFE;
  while (n % 4) msg[n++] = 0x00;

  uint8_t cc[4];
  if (!read_page(3, cc)) { err = "Couldn't read the card. Hold it still and try again."; return false; }
  if (!cc[0] && !cc[1] && !cc[2] && !cc[3]) {
    const uint8_t fresh[4] = {0xE1, 0x10, 0x3E, 0x00};
    if (!write_page(3, fresh)) { err = "Couldn't set up the card."; return false; }
  }
  // Already locked: fine only if it already holds this exact link (a lock that
  // was cut short last time). Then just finish the lock.
  bool already = cc[3] != 0x00;
  if (already) {
    for (size_t p = 0; p < n / 4; p++) {
      uint8_t got[4];
      if (!read_page(4 + p, got) || memcmp(got, msg + p * 4, 4) != 0) {
        err = "This card is locked. Use a new blank one."; return false;
      }
    }
  }

  for (size_t p = 0; !already && p < n / 4; p++)
    if (!write_page(4 + p, msg + p * 4)) { err = "The card moved while writing. Set it down again."; return false; }

  // Read it back: it has to say exactly what we wrote.
  for (size_t p = 0; p < n / 4; p++) {
    uint8_t got[4];
    if (!read_page(4 + p, got) || memcmp(got, msg + p * 4, 4) != 0) {
      err = "The card didn't read back right. Set it down again."; return false;
    }
  }

#if LOCK_CARDS
  // Lock it, so nobody can put a different link on it with their phone.
  // Order matters: the static lock bits also lock page 3, so they go last.
  const uint8_t dyn[4] = {0xFF, 0xFF, 0xFF, 0x00};
  const uint8_t ro[4] = {0xE1, 0x10, 0x3E, 0x0F};
  const uint8_t stat[4] = {0x00, 0x00, 0xFF, 0xFF};
  if (!write_page(0x82, dyn) || !write_page(3, ro) || !write_page(2, stat)) {
    err = "Written, but the lock didn't take. Set it down again."; return false;
  }
#endif
  return true;
}
