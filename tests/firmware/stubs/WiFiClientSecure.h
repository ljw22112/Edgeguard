#pragma once
#include "Arduino.h"
// ESP32 WiFiClientSecure subset: TLS client with a CA certificate (PEM).  tests/firmware/sil keeps the PEM
// and hands it to libmosquitto.
struct WiFiClientSecure {
  const char* ca = nullptr;
  void setCACert(const char* pem) { ca = pem; }
};
