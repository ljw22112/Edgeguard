#pragma once
#include "Arduino.h"
#include "WiFiClientSecure.h"
#include <functional>
// PubSubClient (knolleary) subset used by firmware/common/m2m_mqtt.h.  tests/firmware/sil implements it
// over libmosquitto with TLS, so the software-in-the-loop build talks to a real broker.
struct PubSubClient {
  explicit PubSubClient(WiFiClientSecure& c) : net(&c) {}
  PubSubClient& setServer(const char* host, uint16_t port) { this->host = host; this->port = port; return *this; }
  PubSubClient& setCallback(void (*cb)(char*, uint8_t*, unsigned int)) { callback = cb; return *this; }
  bool setBufferSize(uint16_t) { return true; }
  bool connect(const char* id, const char* user, const char* pass);
  bool connected();
  bool publish(const char* topic, const char* payload);
  bool subscribe(const char* topic);
  bool loop();
  WiFiClientSecure* net;
  const char* host = "";
  uint16_t port = 8883;
  void (*callback)(char*, uint8_t*, unsigned int) = nullptr;
  void* impl = nullptr;
};
