#pragma once
#include "Arduino.h"
struct HTTPClient {
  bool begin(const String& url);
  void addHeader(const String& name, const String& value);
  int POST(const String& body);
  void end();
};
