// EdgeGuard forklift module (ESP32 + MPU6050 + beacon LED + motor driver on the RC car)
//
// - Publishes motion to oneM2M:  <CSE>/forklift_01/motion (its own AE)
//   {id, kind, ts, x, y, speed, heading, yaw_rate}
// - Receives alerts on http://<module-ip>/alert:
//   beacon on/off and the absolute speed limit applied to the drive PWM
// - Also receives <ae>/control on the same URL: adaptive-rate commands and the MEC app's
//   1 s heartbeat.  Speed-limit rules (device_policy.h, same as edgeguard/device_policy.py):
//   hold the limit between refreshes, lift it if the MEC app is alive but stopped refreshing
//   for 5 s (lost "clear"), hold through a short MEC silence, stop if silent > 2 s.
//
// MPU6050 is read over I2C with raw registers (no extra library).
// Local fallback (v0.8): the module's DW1000 runs as a *mobile anchor* (short address 0x20NN).
// Worker tags range it in their normal anchor rounds, so both ends get the distance; the
// module feeds it to speedLimit.onRange() and device_policy.h applies distance + closing-speed
// (time-to-collision) zones while the MEC app is silent for 2 s.
// Cooperative D2D (v0.9, d2d.h): the module broadcasts its state over ESP-NOW every report tick,
// takes workers' states for the 2-D closest-approach rule (while MEC is silent), and relays for
// workers in a radio shadow: their MEC alerts / heartbeats down, their positions up to the CSE.
// If the module itself is in a shadow, a worker tag that still hears MEC relays for it.
// Position comes from a separate UWB tag board on the forklift (worker_tag firmware with
// kind "forklift"; one DW1000 cannot be anchor and tag at once) - stub: readPosition().
// Speed comes from the drive command / wheel encoder (stub: readSpeed()).
// NOTE: written against the ESP32 Arduino core 3.x API; not yet compiled on hardware.

// HIL_MODE 1 (hardware-in-the-loop demo, docs/hardware-demo.md): no UWB / IMU needed - positions come from
// devices/live_devices.py, this board only does what a real device does with the alerts (actuators) and
// confirms it in <CSE>/<DEVICE_ID>/status.  Build with -DHIL_MODE=1 or change the default here.
#ifndef HIL_MODE
#define HIL_MODE 0
#endif
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#ifndef M2M_MQTT
#define M2M_MQTT 0                       // 1: oneM2M MQTT binding over TLS to the site broker (m2m_mqtt.h)
#endif
#if M2M_MQTT
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include "m2m_mqtt.h"       // copy of firmware/common/m2m_mqtt.h (kept identical by tests)
#endif
#include <Wire.h>
#include <ArduinoJson.h>
#include <time.h>
#include <SPI.h>
#include <DW1000Ranging.h>
#include <esp_now.h>
#include "d2d.h"            // copy of firmware/common/d2d.h (kept identical by tests)
#include "d2d_auth.h"       // HMAC + replay guard for D2D frames (copy of firmware/common/d2d_auth.h)
#include "device_policy.h"   // copy of firmware/common/device_policy.h (kept identical by tests)

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASS";
#ifdef SIL_CSE_URL
const char* CSE_URL   = SIL_CSE_URL;                            // software-in-the-loop build (tools/sil_run.py)
#else
const char* CSE_URL   = "http://192.168.0.10:7579/Mobius";
#endif
const char* RVI       = "2a";            // oneM2M release both Mobius 3 and ACME accept (docs/interop-notes.md #5)
#if M2M_MQTT
#ifdef SIL_MQTT_HOST
const char* MQTT_HOST = SIL_MQTT_HOST;                          // software-in-the-loop build (tools/sil_run.py)
const char* MQTT_PASS = SIL_MQTT_PASS;
#else
const char* MQTT_HOST = "192.168.0.10";                         // site broker (scripts/mqtt.sh), TLS on 8883
const char* MQTT_PASS = "CHANGE-ME";                            // this device's broker password
#endif
#ifdef MQTT_CLIENT_CERT                                         // mutual TLS: this device's certificate (CN =
const uint16_t MQTT_PORT = 8884;                                // originator) is its identity, no password
#else
const uint16_t MQTT_PORT = 8883;
#endif
const char* CSE_ID    = "id-in";                                // the CSE's ID and name (ACME IN-CSE defaults)
const char* CSE_RN    = "cse-in";
#ifndef MQTT_CA_PEM                                             // the site CA (scripts/certs.sh, .certs/ca.crt)
#define MQTT_CA_PEM "-----BEGIN CERTIFICATE-----\n...site CA...\n-----END CERTIFICATE-----\n"
#endif
WiFiClientSecure tlsNet;
PubSubClient mqttClient(tlsNet);
m2m::MqttLink m2mLink;
#endif
#ifndef HTTP_PORT
#define HTTP_PORT 80                     // alert listener (the AE's poa)
#endif
const char* ORIGIN    = "SForklift01";        // this device's own AE (config/site.yaml security.originators)
const char* DEVICE_ID = "forklift_01";
const int   BEACON_PIN = 26;
const int   MOTOR_PWM_PIN = 27;
const uint8_t MPU = 0x68;
const float GYRO_LSB = 131.0f;          // +-250 deg/s range
#if HIL_MODE
const float MAX_SPEED = 2.5f;           // HIL: the motor stands for a site forklift (2.5 m/s = full PWM)
#else
const float MAX_SPEED = 1.0f;           // m/s at full drive PWM (calibrate on the RC car)
#endif
policy::ForkliftLimit speedLimit;       // m/s, fail-safe on MEC silence
policy::ReportRate reportRate;          // 10 Hz until told otherwise
const char* PEER_ANCHOR_EUI = "01:20:5B:D5:A9:9A:E2:9C";   // short address 0x2001 (forklift_01)
const int PIN_RST = 17, PIN_IRQ = 34, PIN_SS = 5;
const uint16_t MY_SHORT = 0x2001;
const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
d2d::Inbox inbox;
d2d::Neighbours neighbours;
d2d::ReplayGuard replay;
// Pre-shared site key: provision a random 16+ byte key per site; the same key on every device.
const uint8_t SITE_KEY[] = "CHANGE-ME-site-key-16+bytes";
uint32_t d2dRejected = 0;

int64_t epochMs();
uint32_t nowSeq() {                     // 100 ms units since 2023-11 (NTP clock), 0 if not synced yet
  int64_t ms = epochMs();
  return ms > 1700000000000LL ? (uint32_t)(ms / 100 - 17000000000LL) : 0;
}

void sendFrame(d2d::Frame& f, int repeat = 1) {   // sign once, send `repeat` copies
  strncpy(f.src, DEVICE_ID, sizeof(f.src) - 1);
  uint32_t s = nowSeq();
  static uint32_t lastSeq = 0;
  f.seq = s > lastSeq ? s : lastSeq + 1;            // strictly increasing even within 100 ms
  lastSeq = f.seq;
  d2d::sign(f, SITE_KEY, sizeof(SITE_KEY) - 1);
  for (int i = 0; i < repeat; i++) esp_now_send(BCAST, (const uint8_t*)&f, sizeof(f));
}
float directT = -1e9f;                  // last MEC notification received directly (not relayed)
uint32_t lastRelayPost = 0, lastProbe = 0;

WebServer server(HTTP_PORT);
float heading = 0.0f;                   // rad, 0 = +x of the site frame
float gyroBiasZ = 0.0f;
float speedScale = 1.0f;
bool beacon = false;
uint32_t lastPublish = 0, lastImu = 0, rqi = 0;

// One oneM2M CREATE (POST with ty) into the CSE, over HTTP or the MQTT binding (M2M_MQTT).  Returns an
// HTTP-like status: 201 created, 409 already there, otherwise an error.
int m2mPost(const String& path, int ty, const String& body, const char* tag) {
#if M2M_MQTT
  (void)tag;
  return m2mLink.create(path, ty, body, RVI);
#else
  HTTPClient http;
  http.begin(String(CSE_URL) + path);
  http.addHeader("X-M2M-Origin", ORIGIN);
  http.addHeader("X-M2M-RI", String(tag) + (rqi++));
  http.addHeader("X-M2M-RVI", RVI);
  http.addHeader("Content-Type", String("application/json;ty=") + ty);
  http.addHeader("Accept", "application/json");
  int code = http.POST(body);
  http.end();
  return code;
#endif
}
int baseDuty = 180;                     // nominal drive PWM (0-255)

int64_t epochMs() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

int16_t readGyroZRaw() {
  Wire.beginTransmission(MPU);
  Wire.write(0x47);                     // GYRO_ZOUT_H
  Wire.endTransmission(false);
  Wire.requestFrom(MPU, (uint8_t)2);
  return (int16_t)(Wire.read() << 8 | Wire.read());
}

float readYawRate() {                   // rad/s, CCW positive
  float dps = (readGyroZRaw() - gyroBiasZ) / GYRO_LSB;
  return dps * PI / 180.0f;
}

bool readPosition(float& x, float& y) { x = 0; y = 0; return true; }   // TODO: UWB tag
float readSpeed() { return MAX_SPEED * speedScale; }                   // TODO: encoder (m/s)
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
  f.kind = d2d::FORKLIFT;
  f.mecOk = mecHeard();
  f.x = x; f.y = y; f.vx = vx; f.vy = vy;
  sendFrame(f);
}

void relayUp(const d2d::Frame& f) {     // a worker in a shadow: post its position, at most 5 Hz
  if (millis() - lastRelayPost < 200) return;
  lastRelayPost = millis();
  JsonDocument doc;
  JsonObject con = doc["m2m:cin"]["con"].to<JsonObject>();
  con["id"] = f.id;
  con["kind"] = "worker";
  con["ts"] = epochMs();
  con["x"] = f.x;
  con["y"] = f.y;
  con["relay"] = DEVICE_ID;
  String body;
  serializeJson(doc, body);
  m2mPost(String("/") + DEVICE_ID + "/relay", 4, body, "rl");
}

void handleD2D() {
  d2d::Frame f;
  while (inbox.pop(f)) {
    float t = nowS();
    // authenticity first: wrong key / tampered / replayed / stale frames are dropped
    uint32_t ns = nowSeq();
    if (!d2d::tagOk(f, SITE_KEY, sizeof(SITE_KEY) - 1) || !replay.accept(f.src, f.seq, ns > 1 ? ns : 0)) {
      d2dRejected++;
      continue;
    }
    if (f.type == d2d::STATE) {
      if (f.kind != d2d::WORKER) continue;
      speedLimit.onPeerState(t, f.shortAddr, f.x, f.y, f.vx, f.vy);
      neighbours.seen(f, t);
      if (!f.mecOk && mecHeard()) relayUp(f);
    } else if (f.type == d2d::ALERT && d2d::idIs(f, DEVICE_ID)) {   // relayed MEC alert for me
      beacon = !f.clear && f.beacon;
      speedLimit.onAlert(t, f.clear, f.limit < 0 ? policy::NO_LIMIT : f.limit, f.src);   // keyed by the relaying tag
    } else if (f.type == d2d::HEARTBEAT && !mecHeard()) {
      speedLimit.onHeartbeat(t);
    }
  }
}

void onPeerRange() {                    // a worker tag ranged this forklift's mobile anchor
  DW1000Device* dev = DW1000Ranging.getDistantDevice();
  speedLimit.onRange(millis() / 1000.0, dev->getShortAddress(), dev->getRange());
}

void publishMotion(float x, float y, float v, float yawRate) {
  JsonDocument doc;
  JsonObject con = doc["m2m:cin"]["con"].to<JsonObject>();
  con["id"] = DEVICE_ID;
  con["kind"] = "forklift";
  con["ts"] = epochMs();
  con["x"] = x;
  con["y"] = y;
  con["speed"] = v;
  con["heading"] = heading;
  con["yaw_rate"] = yawRate;
  JsonArray plan = con["plan"].to<JsonArray>();     // the plan it applies: the MEC app re-sends what is missing
  for (const auto& pr : speedLimit.pairs) {
    if (!pr.used) continue;
    JsonArray e = plan.add<JsonArray>();
    e.add(pr.src); e.add(pr.limit); e.add(pr.hasStop ? 1 : 0);
  }
  String body;
  serializeJson(doc, body);
  int code = m2mPost(String("/") + DEVICE_ID + "/motion", 4, body, "fk");
  if (code != 201) Serial.printf("publish failed: %d\n", code);
}

void handleAlert() {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, server.arg("plain"));
  server.sendHeader("X-M2M-RSC", "2000");
  server.send(200, "application/json", "{}");
  if (err) return;
  JsonObject sgn = doc["m2m:sgn"];
  if (sgn["vrq"] | false) return;
  JsonObject alert = sgn["nev"]["rep"]["m2m:cin"]["con"];
  if (alert.isNull()) return;
  float t = nowS();
  speedLimit.onHeartbeat(t);                       // any MEC message: the MEC app is alive
  directT = t;
  if (neighbours.anyOffline(t)) {                  // relay for workers in a radio shadow (one hop)
    d2d::Frame r;
    if (!alert["rates"].isNull()) {
      r.type = d2d::HEARTBEAT;
      sendFrame(r, d2d::RELAY_REPEAT);
    } else {
      const char* wk = alert["worker"] | "";
      if (neighbours.offline(wk, t)) {
        r.type = d2d::ALERT;
        d2d::setId(r, wk);
        String ev = (const char*)(alert["event"] | "");
        r.clear = ev == "clear" || ev == "release";             // GO for the waiting worker
        r.vibrate = alert["actions"][wk]["vibrate"] | false;      // wait keep-alive: neither
        r.level = strcmp(alert["level"] | "SAFE", "DANGER") == 0 ? 2 : 1;
        sendFrame(r, d2d::RELAY_REPEAT);
      }
    }
  }
  if (!alert["rates"].isNull()) {                  // <ae>/control: rate command / heartbeat
    float hz = alert["rates"][DEVICE_ID] | 0.0f;
    if (hz > 0) reportRate.onCommand(t, hz);
    return;
  }
  if (String((const char*)alert["forklift"]) != DEVICE_ID) return;
  String ev = (const char*)(alert["event"] | "");
  if (ev == "wait" || ev == "release" || ev == "aside") return;   // worker-only cues: the speed limit stays
  JsonObject act = alert["actions"][DEVICE_ID];
  bool clear = String((const char*)(alert["event"] | "")) == "clear";
  beacon = !clear && (act["beacon"] | false);
  // Prefer the absolute limit (m/s): a ratio of an already reduced speed would let the truck
  // speed up again.
  float lim = act["speed_limit"].isNull() ? (float)(act["speed_scale"] | 1.0f) * MAX_SPEED
                                          : (float)act["speed_limit"];
  JsonArray stop = act["stop_at"];                 // stop point: the module brakes for it from its own position
  if (!clear && !stop.isNull() && stop.size() == 2) {
    if (act["speed_limit"].isNull()) lim = policy::NO_LIMIT;
    speedLimit.onAlert(t, false, lim, alert["worker"] | "", true, (float)stop[0], (float)stop[1]);
  } else {
    speedLimit.onAlert(t, clear, lim < 0 ? 0.0f : lim, alert["worker"] | "");   // one plan per worker
  }
  Serial.printf("alert %s beacon=%d limit %.2f m/s\n", (const char*)(alert["level"] | "?"), beacon, lim);
}

// Actuator confirmation: what this board is doing now, written to its own AE (<CSE>/<id>/status) on
// every change - the MEC dashboard shows it next to the device (HW check mark).
String lastAck;
void postAck(const String& st) {
  if (st == lastAck) return;
  lastAck = st;
  JsonDocument doc;
  JsonObject con = doc["m2m:cin"]["con"].to<JsonObject>();
  con["id"] = DEVICE_ID;
  con["kind"] = "ack";
#ifdef SIL_CSE_URL
  con["hw"] = "sil";                    // same firmware, compiled for a PC (tools/sil_run.py)
#else
  con["hw"] = "esp32";
#endif
  con["state"] = st;
  con["ts"] = epochMs();
  String body;
  serializeJson(doc, body);
  m2mPost(String("/") + DEVICE_ID + "/status", 4, body, "ack");
}

// oneM2M registration: this device is its own AE (<CSE>/{DEVICE_ID}) with its data container
// under it.  Idempotent (409 = already registered); tools/setup_resources.py adds the ACP.
bool m2mCreate(const String& path, int ty, const String& body) {
  int code = m2mPost(path, ty, body, "reg");
  return code == 201 || code == 409;
}

void registerAE() {
  String poa = String("http://") + WiFi.localIP().toString() + ":" + String(HTTP_PORT) + "/alert";
  bool ae = m2mCreate("", 2, String("{\"m2m:ae\":{\"rn\":\"") + DEVICE_ID +
                      "\",\"api\":\"Nedgeguard.forklift\",\"rr\":true,\"poa\":[\"" + poa + "\"],\"srv\":[\"2a\",\"3\"]}}");
  bool cnt = m2mCreate(String("/") + DEVICE_ID, 3, "{\"m2m:cnt\":{\"rn\":\"motion\"}}");
  m2mCreate(String("/") + DEVICE_ID, 3, "{\"m2m:cnt\":{\"rn\":\"relay\",\"mni\":50}}");   // D2D relay for neighbours
  m2mCreate(String("/") + DEVICE_ID, 3, "{\"m2m:cnt\":{\"rn\":\"status\",\"mni\":50}}");  // actuator confirmations
  Serial.printf("oneM2M AE %s: %s, container motion: %s\n", DEVICE_ID, ae ? "ok" : "failed", cnt ? "ok" : "failed");
}

void setup() {
  Serial.begin(115200);
  pinMode(BEACON_PIN, OUTPUT);
  Wire.begin();
  Wire.beginTransmission(MPU); Wire.write(0x6B); Wire.write(0); Wire.endTransmission();  // wake
  long sum = 0;                                    // gyro bias: keep the car still at boot
  for (int i = 0; i < 500; i++) { sum += readGyroZRaw(); delay(2); }
  gyroBiasZ = sum / 500.0f;
  ledcAttach(MOTOR_PWM_PIN, 20000, 8);             // ESP32 core 3.x
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(250); Serial.print("."); }
#if M2M_MQTT
  tlsNet.setCACert(MQTT_CA_PEM);
#ifdef MQTT_CLIENT_CERT                                           // scripts/device_cert.sh issue <originator>
  tlsNet.setCertificate(MQTT_CLIENT_CERT);
  tlsNet.setPrivateKey(MQTT_CLIENT_KEY);
#endif
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  m2mLink.begin(mqttClient, ORIGIN, CSE_ID, CSE_RN, ORIGIN, MQTT_PASS);   // broker user = originator
#endif
  registerAE();
  Serial.printf("\nIP %s\n", WiFi.localIP().toString().c_str());
  configTime(9 * 3600, 0, "pool.ntp.org");
  server.on("/alert", HTTP_POST, handleAlert);
  server.begin();
#if !HIL_MODE
  DW1000Ranging.initCommunication(PIN_RST, PIN_SS, PIN_IRQ);
  DW1000Ranging.attachNewRange(onPeerRange);
  DW1000Ranging.startAsAnchor(PEER_ANCHOR_EUI, DW1000.MODE_LONGDATA_RANGE_ACCURACY, false);
#endif
  esp_now_init();
  esp_now_register_recv_cb(onD2D);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  esp_now_add_peer(&peer);
  lastImu = micros();
}

void loop() {
#if !HIL_MODE
  DW1000Ranging.loop();
#endif
  server.handleClient();
#if M2M_MQTT
  m2mLink.loop();
#endif
  handleD2D();
  uint32_t now = micros();
  float dt = (now - lastImu) * 1e-6f;
  lastImu = now;
  float yawRate = readYawRate();
  heading += yawRate * dt;                          // integrate gyro (UWB track corrects drift)
  float lim = speedLimit.effective(nowS());          // fail-safe rules in device_policy.h
  speedScale = lim < 0 ? 1.0f : constrain(lim / MAX_SPEED, 0.0f, 1.0f);
  if (lim < 0) beacon = false;
  ledcWrite(MOTOR_PWM_PIN, (int)(baseDuty * speedScale));
  digitalWrite(BEACON_PIN, beacon && (millis() / 250) % 2);   // blink
  postAck(lim < 0 ? String("full speed") : String("limit ") + String(lim, 2) + " m/s");
  if (!HIL_MODE && millis() - lastPublish >= reportRate.periodMs(nowS())) {
    lastPublish = millis();
    float x, y;
    if (readPosition(x, y)) {
      float v = readSpeed(), vx = v * cosf(heading), vy = v * sinf(heading);   // readSpeed() includes the limit
      speedLimit.onOwnState(nowS(), x, y, vx, vy);
      speedLimit.onPose(x, y, cosf(heading), sinf(heading));   // stop points are braked for from here
      sendState(x, y, vx, vy);                     // D2D, works without the network
      if (mecHeard() || millis() - lastProbe > 2000) { lastProbe = millis(); publishMotion(x, y, v, yawRate); }
    }
  }
}
