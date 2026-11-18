#pragma once
#include <string>
#include <cstring>
#include <cctype>
#include <cstdint>
#include <cstdio>
struct String : std::string {
  String() {} String(const char*s):std::string(s){} String(const std::string&s):std::string(s){}
  int indexOf(const char*s) const { auto p=find(s); return p==npos?-1:(int)p; }
  void toLowerCase(){ for(auto&c:*this) c=tolower(c); }
  String& operator+=(char c){ push_back(c); return *this; }
  String& operator=(const char*s){ assign(s); return *this; }
};
inline uint32_t millis(){ static uint32_t t=0; return t+=200; }
struct HardwareSerial { void begin(int,int,int,int){} };
extern HardwareSerial Serial1;
#define SERIAL_8N1 0
