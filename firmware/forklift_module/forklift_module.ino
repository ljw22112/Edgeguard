// EdgeGuard forklift module (ESP32 + MPU6050 + beacon LED + motor driver on the RC car)
//
// - Publishes motion to oneM2M:  <CSE>/EdgeGuard/forklift_01/motion
//   {id, kind, ts, x, y, speed, heading, yaw_rate}
// - Receives alerts on http://<module-ip>/alert:
//   beacon on/off and the absolute speed limit applied to the drive PWM
// - Also receives <ae>/control on the same URL: adaptive-rate commands and the MEC app's
//   1 s heartbeat.  Speed-limit rules (device_policy.h, same as edgeguard/device_policy.py):
//   hold the limit between refreshes, lift it if the MEC app is alive but stopped refreshing
//   for 5 s (lost "clear"), hold through a short MEC silence, stop if silent > 2 s.
//
// MPU6050 is read over I2C with raw registers (no extra library).
// Position comes from a UWB tag on the forklift (stub: readPosition()).
// Speed comes from the drive command / wheel encoder (stub: readSpeed()).
// NOTE: written against the ESP32 Arduino core 3.x API; not yet compiled on hardware.

#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include <time.h>
#include "device_policy.h"   // copy of firmware/common/device_policy.h (kept identical by tests)

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASS";
const char* CSE_URL   = "http://192.168.0.10:7579/Mobius";
const char* ORIGIN    = "CEdgeGuard";
const char* DEVICE_ID = "forklift_01";
const int   BEACON_PIN = 26;
const int   MOTOR_PWM_PIN = 27;
const uint8_t MPU = 0x68;
const float GYRO_LSB = 131.0f;          // +-250 deg/s range
const float MAX_SPEED = 1.0f;           // m/s at full drive PWM (calibrate on the RC car)
policy::ForkliftLimit speedLimit;       // m/s, fail-safe on MEC silence
policy::ReportRate reportRate;          // 10 Hz until told otherwise

WebServer server(80);
float heading = 0.0f;                   // rad, 0 = +x of the site frame
float gyroBiasZ = 0.0f;
float speedScale = 1.0f;
bool beacon = false;
uint32_t lastPublish = 0, lastImu = 0, rqi = 0;
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
  String body;
  serializeJson(doc, body);
  HTTPClient http;
  http.begin(String(CSE_URL) + "/EdgeGuard/" + DEVICE_ID + "/motion");
  http.addHeader("X-M2M-Origin", ORIGIN);
  http.addHeader("X-M2M-RI", String("fk") + (rqi++));
  http.addHeader("X-M2M-RVI", "3");
  http.addHeader("Content-Type", "application/json;ty=4");
  int code = http.POST(body);
  if (code != 201) Serial.printf("publish failed: %d\n", code);
  http.end();
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
  if (!alert["rates"].isNull()) {                  // <ae>/control: rate command / heartbeat
    float hz = alert["rates"][DEVICE_ID] | 0.0f;
    if (hz > 0) reportRate.onCommand(t, hz);
    return;
  }
  if (String((const char*)alert["forklift"]) != DEVICE_ID) return;
  JsonObject act = alert["actions"][DEVICE_ID];
  bool clear = String((const char*)(alert["event"] | "")) == "clear";
  beacon = !clear && (act["beacon"] | false);
  // Prefer the absolute limit (m/s): a ratio of an already reduced speed would let the truck
  // speed up again.
  float lim = act["speed_limit"].isNull() ? (float)(act["speed_scale"] | 1.0f) * MAX_SPEED
                                          : (float)act["speed_limit"];
  speedLimit.onAlert(t, clear, lim < 0 ? 0.0f : lim);
  Serial.printf("alert %s beacon=%d limit %.2f m/s\n", (const char*)(alert["level"] | "?"), beacon, lim);
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
  Serial.printf("\nIP %s\n", WiFi.localIP().toString().c_str());
  configTime(9 * 3600, 0, "pool.ntp.org");
  server.on("/alert", HTTP_POST, handleAlert);
  server.begin();
  lastImu = micros();
}

void loop() {
  server.handleClient();
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
  if (millis() - lastPublish >= reportRate.periodMs(nowS())) {
    lastPublish = millis();
    float x, y;
    if (readPosition(x, y)) publishMotion(x, y, readSpeed(), yawRate);
  }
}
