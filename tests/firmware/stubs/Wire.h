#pragma once
#include "Arduino.h"
struct TwoWire {
  void begin(); void beginTransmission(uint8_t); uint8_t endTransmission(bool stop = true);
  uint8_t requestFrom(uint8_t addr, uint8_t n); int read(); size_t write(uint8_t);
};
extern TwoWire Wire;
