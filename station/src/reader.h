// The card reader (PN532) and the NTAG215 cards: read the link on a card,
// write the link on a blank one, and lock it.
#pragma once
#include <Arduino.h>

enum TagKind {
  TAG_OURS,    // a Sisyphus gift card: code holds its 32-letter code
  TAG_BLANK,   // an empty card we can write
  TAG_OTHER,   // some other card (a hotel key, a card with another link)
};

struct Tag {
  TagKind kind;
  uint8_t uid[7];
  uint8_t uidLen;
  char code[33];
};

bool reader_begin();                    // false if the reader doesn't answer
bool reader_poll(Tag &t);               // true when a card has just been set down
bool reader_still_there();              // the last card is still on the reader
// Write the link for `code` on the card that is on the reader now, read it
// back to check it, then lock it (LOCK_CARDS). On failure, err says why.
bool reader_write(const char *code, String &err);
