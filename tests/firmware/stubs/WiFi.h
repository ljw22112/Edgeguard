#pragma once
#include "Arduino.h"
#define WL_CONNECTED 3
struct IPAddress { String toString() const { return "0.0.0.0"; } };
struct WiFiClass { void begin(const char*, const char*); int status(); IPAddress localIP(); };
extern WiFiClass WiFi;
