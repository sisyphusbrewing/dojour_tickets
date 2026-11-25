#include "reader.h"
#include <cassert>
HardwareSerial Serial1; extern uint8_t mem[135][4];
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
  puts("all good");
}
