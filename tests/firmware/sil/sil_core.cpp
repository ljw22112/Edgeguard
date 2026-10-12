// Software-in-the-loop runtime: the ESP32 sketches compiled for a PC (tools/sil_run.py).
// Implements the Arduino / ESP32 API subset declared in tests/firmware/stubs with real behaviour where it
// matters - HTTP client and server over TCP (oneM2M to the CSE, alert notifications from it), wall clock -
// and records every actuator change (digitalWrite / ledcWrite) as a JSON line on stdout:
//   {"t": <ms since start>, "pin": 25, "value": 1}
// Radio parts (DW1000 UWB, ESP-NOW) and the IMU are absent, as in the firmware's HIL_MODE.
#include "Arduino.h"
#include "HTTPClient.h"
#include "WebServer.h"
#include "WiFi.h"
#include "Wire.h"
#include "DW1000Ranging.h"
#include "esp_now.h"

#include <arpa/inet.h>
#include <chrono>
#include <cstdarg>
#include <cstring>
#include <fcntl.h>
#include <map>
#include <netdb.h>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>

static const auto T0 = std::chrono::steady_clock::now();
uint32_t millis() {
  return (uint32_t)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - T0).count();
}
uint32_t micros() {
  return (uint32_t)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - T0).count();
}
void delay(uint32_t ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
void configTime(long, int, const char*) {}

static std::map<int, long> pins;
static void record(int pin, long v) {
  auto it = pins.find(pin);
  if (it != pins.end() && it->second == v) return;
  pins[pin] = v;
  std::printf("{\"t\": %u, \"pin\": %d, \"value\": %ld}\n", millis(), pin, v);
  std::fflush(stdout);
}
void pinMode(int, int) {}
void digitalWrite(int pin, int v) { record(pin, v ? 1 : 0); }
bool ledcAttach(int, uint32_t, uint8_t) { return true; }
void ledcWrite(int pin, uint32_t duty) { record(pin, (long)duty); }

HardwareSerial Serial;
int HardwareSerial::printf(const char* fmt, ...) {
  char buf[512];
  va_list ap;
  va_start(ap, fmt);
  int n = std::vsnprintf(buf, sizeof buf, fmt, ap);
  va_end(ap);
  std::fprintf(stderr, "[serial] %s", buf);
  return n;
}

WiFiClass WiFi;
void WiFiClass::begin(const char*, const char*) {}
int WiFiClass::status() { return WL_CONNECTED; }
IPAddress WiFiClass::localIP() { return IPAddress(); }

TwoWire Wire;
void TwoWire::begin() {}
void TwoWire::beginTransmission(uint8_t) {}
uint8_t TwoWire::endTransmission(bool) { return 0; }
uint8_t TwoWire::requestFrom(uint8_t, uint8_t n) { return n; }
int TwoWire::read() { return 0; }
size_t TwoWire::write(uint8_t) { return 1; }

DW1000Class DW1000;
const uint8_t DW1000Class::MODE_LONGDATA_RANGE_ACCURACY[3] = {0, 0, 0};
DW1000RangingClass DW1000Ranging;
void DW1000RangingClass::initCommunication(uint8_t, uint8_t, uint8_t) {}
void DW1000RangingClass::attachNewRange(void (*)()) {}
void DW1000RangingClass::startAsTag(const char*, const uint8_t[], bool) {}
void DW1000RangingClass::startAsAnchor(const char*, const uint8_t[], bool) {}
void DW1000RangingClass::loop() {}
DW1000Device* DW1000RangingClass::getDistantDevice() { return nullptr; }
uint16_t DW1000Device::getShortAddress() { return 0; }
float DW1000Device::getRange() { return 0; }
esp_err_t esp_now_init() { return ESP_OK; }
esp_err_t esp_now_register_recv_cb(esp_now_recv_cb_t) { return ESP_OK; }
esp_err_t esp_now_add_peer(const esp_now_peer_info_t*) { return ESP_OK; }
esp_err_t esp_now_send(const uint8_t*, const uint8_t*, size_t) { return ESP_OK; }

// ---------------- HTTP client (one request per begin/POST/end, like the ESP32 HTTPClient)
static std::string g_url;
static std::string g_headers;
bool HTTPClient::begin(const String& url) { g_url = url; g_headers.clear(); return true; }
void HTTPClient::addHeader(const String& n, const String& v) { g_headers += n + ": " + v + "\r\n"; }
void HTTPClient::end() {}
int HTTPClient::POST(const String& body) {
  // http://host:port/path
  std::string u = g_url.substr(g_url.find("//") + 2);
  std::string hostport = u.substr(0, u.find('/'));
  std::string path = u.find('/') == std::string::npos ? "/" : u.substr(u.find('/'));
  std::string host = hostport.substr(0, hostport.find(':'));
  std::string port = hostport.find(':') == std::string::npos ? "80" : hostport.substr(hostport.find(':') + 1);
  addrinfo hints{}, *res = nullptr;
  hints.ai_socktype = SOCK_STREAM;
  if (getaddrinfo(host.c_str(), port.c_str(), &hints, &res) != 0) return -1;
  int fd = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
  timeval tv{3, 0};
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
  int code = -1;
  if (connect(fd, res->ai_addr, res->ai_addrlen) == 0) {
    std::string req = "POST " + path + " HTTP/1.1\r\nHost: " + hostport + "\r\n" + g_headers +
                      "Content-Length: " + std::to_string(body.size()) + "\r\nConnection: close\r\n\r\n" + body;
    send(fd, req.data(), req.size(), 0);
    char buf[256];
    ssize_t n = recv(fd, buf, sizeof buf - 1, 0);
    if (n > 12) { buf[n] = 0; code = std::atoi(buf + 9); }
  }
  close(fd);
  freeaddrinfo(res);
  return code;
}

// ---------------- HTTP server (non-blocking accept in handleClient, like the ESP32 WebServer)
static int g_srv = -1;
static std::map<std::string, std::function<void()>> g_routes;
static std::string g_body, g_resp_headers;
static int g_client = -1;
WebServer::WebServer(int port) {
  g_srv = socket(AF_INET, SOCK_STREAM, 0);
  int one = 1;
  setsockopt(g_srv, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
  sockaddr_in a{};
  a.sin_family = AF_INET;
  a.sin_port = htons(port);
  a.sin_addr.s_addr = htonl(INADDR_ANY);
  if (bind(g_srv, (sockaddr*)&a, sizeof a) != 0) { std::perror("bind"); std::exit(2); }
}
void WebServer::on(const char* uri, HTTPMethod, std::function<void()> fn) { g_routes[uri] = fn; }
void WebServer::begin() { listen(g_srv, 16); fcntl(g_srv, F_SETFL, O_NONBLOCK); }
String WebServer::arg(const char* name) { return std::strcmp(name, "plain") == 0 ? String(g_body) : String(""); }
void WebServer::sendHeader(const String& n, const String& v) { g_resp_headers += n + ": " + v + "\r\n"; }
void WebServer::send(int code, const char* type, const String& body) {
  std::string r = "HTTP/1.1 " + std::to_string(code) + " OK\r\nContent-Type: " + type + "\r\n" + g_resp_headers +
                  "Content-Length: " + std::to_string(body.size()) + "\r\nConnection: close\r\n\r\n" + body;
  ::send(g_client, r.data(), r.size(), 0);
}
void WebServer::handleClient() {
  int c = accept(g_srv, nullptr, nullptr);
  if (c < 0) return;
  timeval tv{2, 0};
  setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
  std::string req;
  char buf[4096];
  size_t need = std::string::npos;
  while (true) {
    ssize_t n = recv(c, buf, sizeof buf, 0);
    if (n <= 0) break;
    req.append(buf, n);
    size_t he = req.find("\r\n\r\n");
    if (he != std::string::npos && need == std::string::npos) {
      size_t cl = req.find("Content-Length:");
      if (cl == std::string::npos) cl = req.find("content-length:");
      need = he + 4 + (cl == std::string::npos ? 0 : std::strtoul(req.c_str() + cl + 15, nullptr, 10));
    }
    if (need != std::string::npos && req.size() >= need) break;
  }
  std::string path = req.substr(req.find(' ') + 1);
  path = path.substr(0, path.find(' '));
  g_body = req.find("\r\n\r\n") == std::string::npos ? "" : req.substr(req.find("\r\n\r\n") + 4);
  g_resp_headers.clear();
  g_client = c;
  auto it = g_routes.find(path);
  if (it != g_routes.end()) it->second();
  else send(404, "text/plain", "");
  close(c);
}

// ---------------- MQTT client over TLS (PubSubClient API on libmosquitto), for M2M_MQTT builds
#ifdef SIL_MQTT
#include "PubSubClient.h"
#include <mosquitto.h>
static PubSubClient* g_ps = nullptr;
static volatile int g_conn = -1;                       // -1 pending, 0 connected, >0 refused / lost
static void on_connect(mosquitto*, void*, int rc) { g_conn = rc; }
static void on_disconnect(mosquitto*, void*, int rc) { g_conn = rc ? rc : 99; }
static void on_message(mosquitto*, void*, const mosquitto_message* m) {
  if (g_ps && g_ps->callback) g_ps->callback(m->topic, (uint8_t*)m->payload, (unsigned)m->payloadlen);
}
bool PubSubClient::connect(const char* id, const char* user, const char* pass) {
  static bool init = false;
  if (!init) { mosquitto_lib_init(); init = true; }
  if (impl) { mosquitto_destroy((mosquitto*)impl); impl = nullptr; }
  mosquitto* m = mosquitto_new(id, true, nullptr);
  impl = m;
  g_ps = this;
  g_conn = -1;
  if (pass && *pass) mosquitto_username_pw_set(m, user, pass);       // with a client certificate: no password
  // the firmware hands over the CA as PEM text (as on the ESP32); libmosquitto wants a file
  auto tmpfile = [](const char* pem, std::string& out) {
    char path[] = "/tmp/egsil_pemXXXXXX";
    int fd = mkstemp(path);
    if (fd >= 0) { if (write(fd, pem, std::strlen(pem)) < 0) {} close(fd); }
    out = path;
  };
  std::string ca, cert, key;
  tmpfile(net->ca, ca);
  if (net->cert && net->key) { tmpfile(net->cert, cert); tmpfile(net->key, key); }   // mutual TLS
  if (mosquitto_tls_set(m, ca.c_str(), nullptr, cert.empty() ? nullptr : cert.c_str(),
                        key.empty() ? nullptr : key.c_str(), nullptr) != MOSQ_ERR_SUCCESS) return false;
  mosquitto_connect_callback_set(m, on_connect);
  mosquitto_disconnect_callback_set(m, on_disconnect);
  mosquitto_message_callback_set(m, on_message);
  if (mosquitto_connect(m, host, port, 30) != MOSQ_ERR_SUCCESS) return false;
  for (int i = 0; i < 300 && g_conn == -1; i++) mosquitto_loop(m, 10, 1);
  std::fprintf(stderr, "[mqtt] connect %s -> %d\n", id, g_conn);
  return g_conn == 0;
}
bool PubSubClient::connected() { return impl && g_conn == 0; }
bool PubSubClient::publish(const char* topic, const char* payload) {
  return mosquitto_publish((mosquitto*)impl, nullptr, topic, (int)std::strlen(payload), payload, 1, false) == MOSQ_ERR_SUCCESS;
}
bool PubSubClient::subscribe(const char* topic) {
  if (mosquitto_subscribe((mosquitto*)impl, nullptr, topic, 1) != MOSQ_ERR_SUCCESS) return false;
  for (int i = 0; i < 20; i++) mosquitto_loop((mosquitto*)impl, 5, 1);    // SUBACK before the first request
  return true;
}
bool PubSubClient::loop() { return impl && mosquitto_loop((mosquitto*)impl, 0, 1) == MOSQ_ERR_SUCCESS; }
#endif

// ---------------- the sketch
void setup();
void loop();
int main() {
  setvbuf(stdout, nullptr, _IOLBF, 0);
  setup();
  while (true) { loop(); std::this_thread::sleep_for(std::chrono::milliseconds(2)); }
}
