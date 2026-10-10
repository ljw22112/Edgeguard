// Minimal Arduino / ESP32 core stand-ins so the sketches can be type-checked on a PC.
// Only declarations the EdgeGuard sketches use; behaviour is not emulated.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cmath>
#include <string>
#include <sys/time.h>
#include <ctime>

#define PI 3.14159265358979f
#define OUTPUT 1
#define INPUT 0
template <class T, class L, class H> T constrain(T v, L lo, H hi) { return v < lo ? lo : (v > hi ? hi : v); }
uint32_t millis();
uint32_t micros();
void delay(uint32_t);
void pinMode(int, int);
void digitalWrite(int, int);
void configTime(long, int, const char*);
bool ledcAttach(int pin, uint32_t freq, uint8_t res);
void ledcWrite(int pin, uint32_t duty);

class String : public std::string {
 public:
  String() = default;
  String(const char* s) : std::string(s ? s : "") {}
  String(const std::string& s) : std::string(s) {}
  String(int v) : std::string(std::to_string(v)) {}
  String(unsigned v) : std::string(std::to_string(v)) {}
  String(long v) : std::string(std::to_string(v)) {}
  String(unsigned long v) : std::string(std::to_string(v)) {}
  String(float v, unsigned char decimals) : std::string(std::to_string(v).substr(0, std::to_string(v).find('.') + 1 + decimals)) {}
  String operator+(const String& o) const { return String(std::string(*this) + std::string(o)); }
  String operator+(const char* o) const { return String(std::string(*this) + o); }
  String operator+(int v) const { return *this + String(v); }
  String operator+(unsigned v) const { return *this + String(v); }
  String operator+(unsigned long v) const { return *this + String(v); }
  // lets ArduinoJson serialise into it (the real core uses String::concat)
  size_t write(uint8_t c) { push_back((char)c); return 1; }
  size_t write(const uint8_t* s, size_t n) { append((const char*)s, n); return n; }
};

struct HardwareSerial {
  void begin(unsigned long) {}
  int printf(const char* fmt, ...) __attribute__((format(printf, 2, 3)));
  void print(const char*) {}
  void println(const char* = "") {}
};
extern HardwareSerial Serial;
