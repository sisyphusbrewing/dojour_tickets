// Talking to the PN532 card reader over its two serial wires ("HSU" mode).
//
// Why this is our own and not a library (Sam at the bench, Nov 25 2026: the
// reader answered at start-up, but a card set on it did nothing, and nothing
// said why): the library we used reads a fixed number of bytes for each
// answer and keeps no record of what went wrong, so there was no telling a
// bad wire from a card the reader couldn't sense. Here every answer is read
// as a whole frame, checked by its own checksum, anything left over from
// before is thrown away first, and everything is counted. The counts are
// what found the real cause that night: the reader was lying on a steel
// table, and steel under its antenna stops it sensing a card at all.
#pragma once
#include <Arduino.h>

bool pn_begin();                                    // wake the reader; false if it doesn't answer
bool pn_find(uint8_t uid[7], uint8_t &len);         // is a card on it right now? Its id if so
bool pn_read(uint8_t page, uint8_t out[4]);         // read one 4-byte page of that card
bool pn_write(uint8_t page, const uint8_t in[4]);   // write one page; true only if the card said yes

// Counts since start-up, for the start-up messages and for noticing a reader
// that has gone quiet: questions sent, ones the reader acknowledged, ones it
// answered properly, cards seen, pages read or written, and how many of
// those the card didn't go along with.
struct PnCounts { uint32_t sent, acked, answered, cards, pages, refused; };
const PnCounts &pn_counts();

// What the reader last learned, for saying WHY a card was turned away (never
// what is on a card): the kind of chip in the last card it found (two "type"
// bytes and one "kind" byte every card gives when it is found: 00 44 / 00 is
// the NTAG family our cards are, 00 04 / 08 is the Mifare card that comes in
// the bag with the reader), how long its id is, and the reader's own code for
// the last page that failed: 01 the card didn't answer in time, 02 or 03 or
// 05 its answer was damaged on the way, 14 the card wants a password first
// (not one of ours), 27 the reader has lost hold of the card; -1 means the
// reader itself gave no proper answer.
struct PnLast { uint8_t type[2], kind, idLen; int16_t why; };
const PnLast &pn_last();
