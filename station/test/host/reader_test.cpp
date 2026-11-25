#include "reader.h"
#include <cassert>
HardwareSerial Serial1; extern uint8_t mem[135][4]; extern int fake_drop_every, fake_drops; extern uint8_t fake_id;
int main(){
  // blank NTAG215 as shipped
  uint8_t cc[4]={0xE1,0x10,0x3E,0x00}; memcpy(mem[3],cc,4); mem[4][0]=0x03; mem[4][1]=0; mem[4][2]=0xFE;
  Tag t; assert(reader_poll(t)); assert(t.kind==TAG_BLANK);
  String err; const char*code="0123456789abcdef0123456789abcdef";
  assert(reader_write(code,err));
  assert(mem[3][3]==0x0F && mem[2][2]==0xFF && mem[2][3]==0xFF && mem[0x82][0]==0xFF);
  // print the NDEF bytes
  for(int p=4;p<4+20;p++) for(int i=0;i<4;i++) printf("%02X ",mem[p][i]); printf("\n");
  for(int k=0;k<5;k++) millis();
  for(int k=0;k<10;k++) millis();
  Tag u; assert(reader_poll(u)); printf("kind=%d code=%s\n",u.kind,u.code); assert(u.kind==TAG_OURS && !strcmp(u.code,code));
  assert(reader_write(code,err)); assert(!reader_write("ffffffffffffffffffffffffffffffff",err)); printf("other code on locked: %s\n",err.c_str());
  // a card with someone else's link
  memset(mem,0,sizeof mem); memcpy(mem[3],cc,4);
  const uint8_t other[]={0x03,0x0F,0xD1,0x01,0x0B,0x55,0x04,'e','x','a','m','p','l','e','.','c','o','m',0xFE,0,0};
  memcpy(mem[4],other,sizeof other); for(int k=0;k<10;k++) millis();
  Tag o; assert(reader_poll(o)); assert(o.kind==TAG_OTHER);
  printf("why: %s\n", reader_card_note().c_str());
  assert(reader_card_note().find("isn't our link") != std::string::npos);

  // A weak signal: every 7th page fails and the card lets go. The station
  // finds the card again each time and carries on, so a blank is still read
  // as a blank, written, read back and locked.
  memset(mem,0,sizeof mem); memcpy(mem[3],cc,4); mem[4][0]=0x03; mem[4][2]=0xFE;
  fake_drop_every=7; fake_drops=0; for(int k=0;k<10;k++) millis();
  Tag w; assert(reader_poll(w)); assert(w.kind==TAG_BLANK); assert(fake_drops>=4);
  assert(reader_write(code,err)); assert(mem[3][3]==0x0F && mem[2][2]==0xFF);
  for(int k=0;k<10;k++) millis();
  Tag w2; assert(reader_poll(w2)); assert(w2.kind==TAG_OURS && !strcmp(w2.code,code));
  printf("weak signal: let go %d times, still read and written\n", fake_drops);

  // A different card slid into its place half way through: stop, don't carry on with the wrong card.
  // (Seen as a new card it is turned away, with the reason kept.)
  fake_drop_every=5; fake_id=2; for(int k=0;k<10;k++) millis();
  Tag x; assert(reader_poll(x));        // card 2 is the one being read now
  fake_drop_every=0; fake_id=3;         // card 3 takes its place
  fake_drop_every=1;                    // and the very next page fails
  assert(!reader_write(code,err));
  fake_drop_every=0; fake_id=1;

  // A card that can't be read at all says so, with the reader's reason.
  fake_drop_every=1; for(int k=0;k<10;k++) millis();
  Tag n; assert(reader_poll(n)); assert(n.kind==TAG_OTHER);
  printf("why: %s\n", reader_card_note().c_str());
  assert(reader_card_note().find("couldn't read it (reader code 01)") != std::string::npos);
  assert(reader_card_note().find("chip 0044/00, 7-byte id") == 0);
  fake_drop_every=0;
  puts("all good");
}
