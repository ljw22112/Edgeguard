// EdgeGuard forklift module (ESP32 + MPU6050 + beacon LED + motor driver on the RC car)
//
// - Publishes motion to oneM2M:  <CSE>/EdgeGuard/forklift_01/motion
//   {id, kind, ts, x, y, speed, heading, yaw_rate}
// - Receives alerts on http://<module-ip>/alert:
//   beacon on/off and speed_scale (0..1) applied to the drive PWM
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

const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASS";
const char* CSE_URL   = "http://192.168.0.10:7579/Mobius";
const char* ORIGIN    = "CEdgeGuard";
const char* DEVICE_ID = "forklift_01";
const int   BEACON_PIN = 26;
const int   MOTOR_PWM_PIN = 27;
const uint32_t PUBLISH_MS = 100;
const uint8_t MPU = 0x68;
const float GYRO_LSB = 131.0f;          // +-250 deg/s range
const float MAX_SPEED = 1.0f;           // m/s at full drive PWM (calibrate on the RC car)
uint32_t lastAlertMs = 0;

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
float readSpeed() { return 1.0f * speedScale; }                        // TODO: encoder (m/s)

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
  if (alert.isNull() || String((const char*)alert["forklift"]) != DEVICE_ID) return;
  JsonObject act = alert["actions"][DEVICE_ID];
  beacon = act["beacon"] | false;
  // Prefer the absolute limit (m/s): a ratio of an already reduced speed would let the truck
  // speed up again. Hold it until a "clear" alert (or the 5 s failsafe in loop()).
  if (!act["speed_limit"].isNull()) {
    speedScale = constrain((float)act["speed_limit"] / MAX_SPEED, 0.0f, 1.0f);
  } else {
    speedScale = constrain((float)(act["speed_scale"] | 1.0f), 0.0f, 1.0f);
  }
  lastAlertMs = millis();
  Serial.printf("alert %s beacon=%d speed x%.2f\n", (const char*)(alert["level"] | "?"), beacon, speedScale);
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
  if (speedScale < 1.0f && millis() - lastAlertMs > 5000) speedScale = 1.0f;   // failsafe
  ledcWrite(MOTOR_PWM_PIN, (int)(baseDuty * speedScale));
  digitalWrite(BEACON_PIN, beacon && (millis() / 250) % 2);   // blink
  if (millis() - lastPublish >= PUBLISH_MS) {
    lastPublish = millis();
    float x, y;
    if (readPosition(x, y)) publishMotion(x, y, readSpeed(), yawRate);
  }
}
