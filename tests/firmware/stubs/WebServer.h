#pragma once
#include "Arduino.h"
#include <functional>
enum HTTPMethod { HTTP_GET, HTTP_POST };
struct WebServer {
  explicit WebServer(int port);
  void on(const char* uri, HTTPMethod m, std::function<void()> fn);
  void begin();
  void handleClient();
  String arg(const char* name);
  void sendHeader(const String& n, const String& v);
  void send(int code, const char* type, const String& body);
};
