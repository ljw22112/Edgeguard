// oneM2M MQTT binding (TS-0010) for the EdgeGuard devices, over TLS.
//
// One TLS connection to the site broker replaces an HTTP request per sample: requests are published on
//   /oneM2M/req/<originator>/<CSE-ID>/json        as oneM2M request primitives (JSON)
// and the CSE answers on /oneM2M/resp/<originator>/<CSE-ID>/json.  The broker authenticates the device
// (username = originator, password) and its ACL lets it publish only under its own originator
// (scripts/mqtt.sh).  Alerts still arrive as HTTP notifications on the device's alert listener: ACME's
// MQTT binding cannot yet send requests to an AE (ankraft/ACME-oneM2M-CSE#200).
//
// Used by worker_tag.ino and forklift_module.ino when built with M2M_MQTT=1 (PubSubClient +
// WiFiClientSecure on the ESP32; tests/firmware/sil implements the same API over libmosquitto).
// Copy of firmware/common/m2m_mqtt.h (kept identical by tests).
#pragma once
#include <PubSubClient.h>

namespace m2m {

struct MqttLink {
  PubSubClient* mq = nullptr;
  const char* origin = "";
  const char* cseId = "";         // e.g. "id-in" (no leading slash)
  const char* cseRn = "";         // e.g. "cse-in"
  const char* user = "";
  const char* pass = "";
  String reqTopic, respTopic, waitRqi;
  int lastRsc = 0;
  uint32_t seq = 0;
  uint32_t requests = 0, timeouts = 0;

  static MqttLink*& self() { static MqttLink* p = nullptr; return p; }

  static void onMessage(char* topic, uint8_t* payload, unsigned int len) {
    MqttLink* l = self();
    if (!l || l->waitRqi.length() == 0) return;
    String msg;
    msg.reserve(len);
    for (unsigned int i = 0; i < len; i++) msg += (char)payload[i];
    // the response primitive carries our rqi and rsc; no full JSON parse needed on the device
    String key = String("\"rqi\":\"") + l->waitRqi + "\"";
    if (msg.indexOf(key) < 0 && msg.indexOf(String("\"rqi\": \"") + l->waitRqi + "\"") < 0) return;
    int p = msg.indexOf("\"rsc\":");
    if (p < 0) return;
    p += 6;
    while (p < (int)msg.length() && (msg[p] == ' ' || msg[p] == '"')) p++;
    l->lastRsc = atoi(msg.c_str() + p);
    (void)topic;
  }

  void begin(PubSubClient& client, const char* originator, const char* cseIdent, const char* cseName,
             const char* username, const char* password) {
    mq = &client;
    origin = originator; cseId = cseIdent; cseRn = cseName; user = username; pass = password;
    reqTopic = String("/oneM2M/req/") + origin + "/" + cseId + "/json";
    respTopic = String("/oneM2M/resp/") + origin + "/" + cseId + "/json";
    self() = this;
    mq->setCallback(onMessage);
    mq->setBufferSize(2048);
  }

  bool ensure() {
    if (mq->connected()) return true;
    if (!mq->connect(origin, user, pass)) return false;
    return mq->subscribe(respTopic.c_str());
  }

  // oneM2M CREATE of a resource of type `ty` under `path` ("" = CSE root, "/worker_01", ...).
  // Returns an HTTP-like status (201 created, 409 exists, 4xx / 5xx error, -1 no response) so the
  // sketches keep one code path for both transports.
  int create(const String& path, int ty, const String& body, const char* rvi, uint32_t timeoutMs = 1500) {
    if (!ensure()) return -1;
    requests++;
    waitRqi = String("mq") + String((unsigned long)(++seq));
    lastRsc = 0;
    String prim = String("{\"op\":1,\"to\":\"") + cseRn + path + "\",\"fr\":\"" + origin + "\",\"rqi\":\"" + waitRqi +
                  "\",\"rvi\":\"" + rvi + "\",\"ty\":" + String(ty) + ",\"pc\":" + body + "}";
    if (!mq->publish(reqTopic.c_str(), prim.c_str())) { waitRqi = ""; return -1; }
    uint32_t t0 = millis();
    while (lastRsc == 0 && millis() - t0 < timeoutMs) { mq->loop(); delay(2); }
    waitRqi = "";
    if (lastRsc == 0) { timeouts++; return -1; }
    switch (lastRsc) {
      case 2001: return 201;
      case 2000: return 200;
      case 4105: return 409;
      case 4004: return 404;
      case 4103: return 403;
      default: return lastRsc >= 5000 ? 500 : 400;
    }
  }

  void loop() { if (mq->connected()) mq->loop(); }
};

}  // namespace m2m
