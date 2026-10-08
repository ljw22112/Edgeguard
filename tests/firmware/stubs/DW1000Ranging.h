// API subset of arduino-dw1000 (thotro) used by the worker tag and the forklift module.
#pragma once
#include "Arduino.h"
struct DW1000Device { uint16_t getShortAddress(); float getRange(); };
struct DW1000Class { static const uint8_t MODE_LONGDATA_RANGE_ACCURACY[3]; };
extern DW1000Class DW1000;
struct DW1000RangingClass {
  void initCommunication(uint8_t rst, uint8_t ss, uint8_t irq);
  void attachNewRange(void (*fn)());
  void startAsTag(const char* address, const uint8_t mode[], bool randomShortAddress = true);
  void startAsAnchor(const char* address, const uint8_t mode[], bool randomShortAddress = true);
  void loop();
  DW1000Device* getDistantDevice();
};
extern DW1000RangingClass DW1000Ranging;
