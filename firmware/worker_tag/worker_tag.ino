// EdgeGuard worker tag (ESP32 + DW1000 UWB + vibration motor + LED)
//
// - Publishes the worker's position to oneM2M:  <CSE>/EdgeGuard/worker_01/location
// - Receives alert notifications from the CSE on  http://<tag-ip>/alert
//   (add that URL to `alert_subscribers` in config/edgeguard.yaml, then run
//    tools/setup_resources.py)
//
// Libraries: ArduinoJson 7.x.  UWB ranging/trilateration is stubbed in
// readPosition() - replace it with the DW1000 anchor code in W3.
// NOTE: written against the ESP32 Arduino core 3.x API; not yet compiled on hardware.

#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <time.h>

// ---------- settings ----------
const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASS";
const char* CSE_URL   = "http://192.168.0.10:7579/Mobius";     // Mobius; ACME: http://<host>:8080/cse-in
const char* ORIGIN    = "CEdgeGuard";
const char* DEVICE_ID = "worker_01";
const int   MOTOR_PIN = 25;
const int   LED_PIN   = 2;
const uint32_t PUBLISH_MS = 100;                                // 10 Hz

WebServer server(80);
uint32_t vibrateUntil = 0;
uint32_t lastPublish = 0;
uint32_t rqi = 0;

int64_t epochMs() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

// TODO(W3): replace with DW1000 two-way ranging to 3-4 anchors + trilateration.
bool readPosition(float& x, float& y) {
  x = 0.0f;
  y = 0.0f;
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
}

void loop() {
  server.handleClient();
  bool on = millis() < vibrateUntil;
  digitalWrite(MOTOR_PIN, on);
  digitalWrite(LED_PIN, on);
  if (millis() - lastPublish >= PUBLISH_MS) {
    lastPublish = millis();
    float x, y;
    if (readPosition(x, y)) publishLocation(x, y);
  }
}
