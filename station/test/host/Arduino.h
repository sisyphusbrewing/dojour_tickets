#pragma once
// A stand-in for the board, so the card code can be checked on a computer.
#include <string>
#include <cstring>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <vector>
#include <functional>
struct String : std::string {
  String() {} String(const char*s):std::string(s){} String(const std::string&s):std::string(s){}
  int indexOf(const char*s) const { auto p=find(s); return p==npos?-1:(int)p; }
  void toLowerCase(){ for(auto&c:*this) c=tolower(c); }
  String& operator+=(char c){ push_back(c); return *this; }
  String& operator=(const char*s){ assign(s); return *this; }
};
// The clock jumps ahead on every look: 200 ms for the card test (so "the card
// was lifted" happens quickly), 1 ms for the reader-link test.
inline uint32_t &fake_step(){ static uint32_t s=200; return s; }
inline uint32_t millis(){ static uint32_t t=0; return t+=fake_step(); }
inline void delay(int){}
// A serial port whose other end is a function: whatever is written is handed
// to on_write, which may put an answer in rx.
struct HardwareSerial {
  std::deque<uint8_t> rx; std::vector<uint8_t> tx;
  std::function<void(HardwareSerial&, const uint8_t*, size_t)> on_write;
  void begin(int,int,int,int){}
  size_t write(const uint8_t*b, size_t n){ tx.insert(tx.end(), b, b+n); if(on_write) on_write(*this,b,n); return n; }
  int available(){ return (int)rx.size(); }
  int read(){ if(rx.empty()) return -1; uint8_t b=rx.front(); rx.pop_front(); return b; }
};
extern HardwareSerial Serial1;
#define SERIAL_8N1 0
