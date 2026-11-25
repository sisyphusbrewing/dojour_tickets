// Talking to the PN532 card reader over its two serial wires ("HSU" mode).
//
// Why this is our own and not a library (Sam at the bench, Nov 25 2026: the
// reader answered at start-up, but a card set on it did nothing): the library
// we used read a fixed number of bytes for each answer. Over serial wires the
// reader's answers come in different lengths, so after the first card the two
// sides were out of step and every later answer was read from the wrong
// place. Here every answer is read as a whole frame, checked by its own
// checksum, and anything left over from before is thrown away first.
#pragma once
#include <Arduino.h>

bool pn_begin();                                    // wake the reader; false if it doesn't answer
bool pn_find(uint8_t uid[7], uint8_t &len);         // is a card on it right now? Its id if so
bool pn_read(uint8_t page, uint8_t out[4]);         // read one 4-byte page of that card
bool pn_write(uint8_t page, const uint8_t in[4]);   // write one page; true only if the card said yes

// Counts since start-up, for the start-up messages and for noticing a reader
// that has gone quiet: questions sent, ones the reader acknowledged, ones it
// answered properly, and cards seen.
struct PnCounts { uint32_t sent, acked, answered, cards; };
const PnCounts &pn_counts();
