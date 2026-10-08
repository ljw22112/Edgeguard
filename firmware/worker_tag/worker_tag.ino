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
// NOTE: written against the ESP32 Arduino core 3.x API; not yet compiled on hardware.

#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <SPI.h>
#include <DW1000Ranging.h>
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
  if (!alert.isNull()) peerGuard.onHeartbeat(millis() / 1000.0f); // any MEC message: MEC alive
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
  DW1000Ranging.startAsTag("7D:00:22:EA:82:60:3B:9C", DW1000.MODE_LONGDATA_RANGE_ACCURACY);
}

void loop() {
  DW1000Ranging.loop();
  server.handleClient();
  if (peerGuard.vibrateLocal(millis() / 1000.0)) vibrateUntil = millis() + 300;   // MEC silent: local rule
  bool on = millis() < vibrateUntil;
  digitalWrite(MOTOR_PIN, on);
  digitalWrite(LED_PIN, on);
  if (millis() - lastPublish >= reportRate.periodMs(millis() / 1000.0f)) {
    lastPublish = millis();
    float x, y;
    if (readPosition(x, y)) publishLocation(x, y);
  }
}
