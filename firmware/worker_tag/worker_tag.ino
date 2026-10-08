// EdgeGuard worker tag (ESP32 + DW1000 UWB + vibration motor + LED)
//
// - Publishes the worker's position to oneM2M:  <CSE>/EdgeGuard/worker_01/location
// - Receives alert notifications from the CSE on  http://<tag-ip>/alert
//   (add that URL to `alert_subscribers` in config/edgeguard.yaml, then run
//    tools/setup_resources.py - it subscribes the URL to <ae>/alert and <ae>/control)
// - Follows adaptive-rate commands from <ae>/control ({"rates": {id: hz}}, 10 Hz near
//   forklifts, 2 Hz otherwise); without a command for 6 s it reports at 10 Hz again
//
// Libraries: ArduinoJson 7.x, arduino-dw1000 (DW1000Ranging, thotro).
// Ranging: the tag does two-way ranging with 3-4 anchors; positions are solved with
// firmware/common/uwb_position.h (least squares + NLOS anchor rejection).
// Local fallback (v0.8): every forklift module runs its DW1000 as a *mobile anchor* with a short
// address 0x20NN, so the same ranging rounds also give this tag its distance to each nearby
// forklift - no extra protocol.  Those ranges are not used for positioning; they feed the local
// rule in device_policy.h, which vibrates the tag while the MEC app is silent and a forklift is
// close or closing (vibrateLocal).  arduino-dw1000 ranges at most MAX_DEVICES (default 4) devices:
// set it to 8 in DW1000Ranging.h for 4 anchors + up to 4 forklifts.
// Cooperative D2D (v0.9, d2d.h): the tag broadcasts its state over ESP-NOW every report tick and
// listens to forklifts' states (2-D closest-approach rule while MEC is silent).  If it still hears
// the MEC app it relays: MEC alerts / heartbeats to a forklift that reported mecOk = 0, and that
// forklift's state up to the CSE (same originator).  ESP-NOW shares the Wi-Fi channel of the AP.
// NOTE: written against the ESP32 Arduino core 3.x API; not yet compiled on hardware.

#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <SPI.h>
#include <DW1000Ranging.h>
#include <esp_now.h>
#include "d2d.h"            // copy of firmware/common/d2d.h (kept identical by tests)
#include <time.h>
#include "uwb_position.h"   // copy of firmware/common/uwb_position.h (kept identical by tests)
#include "device_policy.h"  // copy of firmware/common/device_policy.h (rate commands)

// ---------- settings ----------
const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASS";
const char* CSE_URL   = "http://192.168.0.10:7579/Mobius";     // Mobius; ACME: http://<host>:8080/cse-in
const char* ORIGIN    = "CEdgeGuard";
const char* DEVICE_ID = "worker_01";
const int   MOTOR_PIN = 25;
const int   LED_PIN   = 2;
policy::ReportRate reportRate;                                  // 10 Hz until told otherwise
policy::ForkliftLimit peerGuard;                                // local rule on forklift ranges
const uint16_t FORKLIFT_ADDR_BASE = 0x2000;                     // forklift mobile anchors 0x20NN
const char* TAG_EUI = "01:10:22:EA:82:60:3B:9C";                // fixed short address 0x1001
const uint16_t MY_SHORT = 0x1001;
const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
d2d::Inbox inbox;
d2d::Neighbours neighbours;
float lastFixX = 0, lastFixY = 0, lastFixT = -1;
uint32_t lastRelayPost = 0, lastProbe = 0;
float directT = -1e9f;                  // last MEC notification received directly (not relayed)

WebServer server(80);
uint32_t vibrateUntil = 0;
uint32_t lastPublish = 0;
uint32_t rqi = 0;

int64_t epochMs() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

// ---------- UWB ----------
// Anchor positions in site metres (measure once with a tape / laser meter).
const uint16_t ANCHOR_ADDR[4] = {0x1781, 0x1782, 0x1783, 0x1784};
const uwb::Anchor ANCHORS[4] = {{0, 0, 3.0f}, {20, 0, 3.0f}, {20, 12, 3.0f}, {0, 12, 3.0f}};
const float TAG_HEIGHT = 1.2f;          // tag worn on the shoulder strap
const uint32_t RANGE_MAX_AGE_MS = 300;  // ranges older than this are not used
float rangeM[4] = {0, 0, 0, 0};
uint32_t rangeAt[4] = {0, 0, 0, 0};
const int PIN_RST = 27, PIN_IRQ = 34, PIN_SS = 4;

void onNewRange() {
  DW1000Device* dev = DW1000Ranging.getDistantDevice();
  uint16_t addr = dev->getShortAddress();
  for (int i = 0; i < 4; i++) {
    if (addr == ANCHOR_ADDR[i]) { rangeM[i] = dev->getRange(); rangeAt[i] = millis(); }
  }
  if ((addr & 0xFF00) == FORKLIFT_ADDR_BASE)                    // a forklift's mobile anchor
    peerGuard.onRange(millis() / 1000.0, addr, dev->getRange());
}

bool readPosition(float& x, float& y) {
  uwb::Anchor a[4];
  float d[4];
  int n = 0;
  for (int i = 0; i < 4; i++) {
    if (rangeAt[i] && millis() - rangeAt[i] < RANGE_MAX_AGE_MS) { a[n] = ANCHORS[i]; d[n] = rangeM[i]; n++; }
  }
  if (n < 3) return false;              // not enough anchors: stay silent, MEC falls back
  uwb::Fix f = uwb::locate(a, d, n, TAG_HEIGHT);
  if (!f.ok || f.rms > 0.5f) return false;
  x = f.x;
  y = f.y;
  return true;
}

float nowS() { return millis() / 1000.0f; }
bool mecHeard() { return nowS() - directT <= policy::SILENCE_S; }   // own link to the MEC app

void onD2D(const esp_now_recv_info_t*, const uint8_t* data, int len) {
  if (d2d::valid(data, len)) inbox.push(data);
}

void sendState(float x, float y, float vx, float vy) {
  d2d::Frame f;
  f.type = d2d::STATE;
  d2d::setId(f, DEVICE_ID);
  f.shortAddr = MY_SHORT;
  f.kind = d2d::WORKER;
  f.mecOk = mecHeard();
  f.x = x; f.y = y; f.vx = vx; f.vy = vy;
  esp_now_send(BCAST, (const uint8_t*)&f, sizeof(f));
}

// relay a forklift's state (it cannot reach the CSE) - at most 5 Hz
void relayUp(const d2d::Frame& f) {
  if (millis() - lastRelayPost < 200) return;
  lastRelayPost = millis();
  JsonDocument doc;
  JsonObject con = doc["m2m:cin"]["con"].to<JsonObject>();
  con["id"] = f.id;
  con["kind"] = "forklift";
  con["ts"] = epochMs();
  con["x"] = f.x;
  con["y"] = f.y;
  con["speed"] = sqrtf(f.vx * f.vx + f.vy * f.vy);
  con["heading"] = atan2f(f.vy, f.vx);
  con["relay"] = DEVICE_ID;
  String body;
  serializeJson(doc, body);
  HTTPClient http;
  http.begin(String(CSE_URL) + "/EdgeGuard/" + f.id + "/motion");
  http.addHeader("X-M2M-Origin", ORIGIN);
  http.addHeader("X-M2M-RI", String("rl") + (rqi++));
  http.addHeader("X-M2M-RVI", "3");
  http.addHeader("Content-Type", "application/json;ty=4");
  http.POST(body);
  http.end();
}

void handleD2D() {
  d2d::Frame f;
  while (inbox.pop(f)) {
    float t = nowS();
    if (f.type == d2d::STATE) {
      if (f.kind != d2d::FORKLIFT) continue;              // workers do not collide with workers
      peerGuard.onPeerState(t, f.shortAddr, f.x, f.y, f.vx, f.vy);
      neighbours.seen(f, t);
      if (!f.mecOk && mecHeard()) relayUp(f);
    } else if (f.type == d2d::ALERT && d2d::idIs(f, DEVICE_ID)) {   // relayed MEC alert for me
      peerGuard.onHeartbeat(t);
      if (f.vibrate) vibrateUntil = millis() + (f.level >= 2 ? 1500 : 600);
    } else if (f.type == d2d::HEARTBEAT && !mecHeard()) {
      peerGuard.onHeartbeat(t);
    }
  }
}

void publishLocation(float x, float y) {
  JsonDocument doc;
  JsonObject con = doc["m2m:cin"]["con"].to<JsonObject>();
  con["id"] = DEVICE_ID;
  con["kind"] = "worker";
  con["ts"] = epochMs();
  con["x"] = x;
  con["y"] = y;
  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.begin(String(CSE_URL) + "/EdgeGuard/" + DEVICE_ID + "/location");
  http.addHeader("X-M2M-Origin", ORIGIN);
  http.addHeader("X-M2M-RI", String("tag") + (rqi++));
  http.addHeader("X-M2M-RVI", "3");
  http.addHeader("Content-Type", "application/json;ty=4");
  http.addHeader("Accept", "application/json");
  int code = http.POST(body);
  if (code != 201) Serial.printf("publish failed: %d\n", code);
  http.end();
}

// oneM2M notification: {"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": {...alert...}}}}}}
void handleAlert() {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, server.arg("plain"));
  server.sendHeader("X-M2M-RSC", "2000");
  server.send(200, "application/json", "{}");
  if (err) return;
  JsonObject sgn = doc["m2m:sgn"];
  if (sgn["vrq"] | false) return;                                 // subscription verification
  JsonObject alert = sgn["nev"]["rep"]["m2m:cin"]["con"];
  float t = nowS();
  if (!alert.isNull()) { peerGuard.onHeartbeat(t); directT = t; } // any MEC message: MEC alive
  // relay for forklifts in a radio shadow (one hop)
  if (!alert.isNull() && neighbours.anyOffline(t)) {
    d2d::Frame r;
    if (!alert["rates"].isNull()) {
      r.type = d2d::HEARTBEAT;
      for (int i = 0; i < d2d::RELAY_REPEAT; i++) esp_now_send(BCAST, (const uint8_t*)&r, sizeof(r));
    } else {
      const char* fk = alert["forklift"] | "";
      if (neighbours.offline(fk, t)) {
        r.type = d2d::ALERT;
        d2d::setId(r, fk);
        JsonObject act = alert["actions"][fk];
        r.clear = String((const char*)(alert["event"] | "")) == "clear";
        r.beacon = act["beacon"] | false;
        r.limit = act["speed_limit"].isNull() ? -1.0f : (float)act["speed_limit"];
        r.level = strcmp(alert["level"] | "SAFE", "DANGER") == 0 ? 2 : 1;
        for (int i = 0; i < d2d::RELAY_REPEAT; i++) esp_now_send(BCAST, (const uint8_t*)&r, sizeof(r));
      }
    }
  }
  if (!alert["rates"].isNull()) {                                 // <ae>/control: rate command / heartbeat
    float hz = alert["rates"][DEVICE_ID] | 0.0f;
    if (hz > 0) reportRate.onCommand(millis() / 1000.0f, hz);
    return;
  }
  if (alert.isNull() || String((const char*)alert["worker"]) != DEVICE_ID) return;
  bool vibrate = alert["actions"][DEVICE_ID]["vibrate"] | false;
  const char* level = alert["level"] | "SAFE";
  // DANGER: continuous 1.5 s, WARNING: 0.6 s pulse
  vibrateUntil = vibrate ? millis() + (strcmp(level, "DANGER") == 0 ? 1500 : 600) : 0;
  Serial.printf("alert %s vibrate=%d\n", level, vibrate);
}

void setup() {
  Serial.begin(115200);
  pinMode(MOTOR_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(250); Serial.print("."); }
  Serial.printf("\nIP %s\n", WiFi.localIP().toString().c_str());
  configTime(9 * 3600, 0, "pool.ntp.org");                        // timestamps for latency
  server.on("/alert", HTTP_POST, handleAlert);
  server.begin();
  DW1000Ranging.initCommunication(PIN_RST, PIN_SS, PIN_IRQ);
  DW1000Ranging.attachNewRange(onNewRange);
  DW1000Ranging.startAsTag(TAG_EUI, DW1000.MODE_LONGDATA_RANGE_ACCURACY, false);
  esp_now_init();
  esp_now_register_recv_cb(onD2D);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  esp_now_add_peer(&peer);
}

void loop() {
  DW1000Ranging.loop();
  server.handleClient();
  handleD2D();
  if (peerGuard.vibrateLocal(millis() / 1000.0)) vibrateUntil = millis() + 300;   // MEC silent: local rule
  bool on = millis() < vibrateUntil;
  digitalWrite(MOTOR_PIN, on);
  digitalWrite(LED_PIN, on);
  if (millis() - lastPublish >= reportRate.periodMs(millis() / 1000.0f)) {
    lastPublish = millis();
    float x, y;
    if (readPosition(x, y)) {
      float t = nowS(), vx = 0, vy = 0;
      if (lastFixT > 0 && t - lastFixT > 0.05f && t - lastFixT < 1.0f) {
        vx = (x - lastFixX) / (t - lastFixT);
        vy = (y - lastFixY) / (t - lastFixT);
      }
      lastFixX = x; lastFixY = y; lastFixT = t;
      peerGuard.onOwnState(t, x, y, vx, vy);
      sendState(x, y, vx, vy);                                     // D2D, works without the network
      // in a radio shadow an HTTP POST would block the loop; probe every 2 s, a neighbour relays meanwhile
      if (mecHeard() || millis() - lastProbe > 2000) { lastProbe = millis(); publishLocation(x, y); }
    }
  }
}
