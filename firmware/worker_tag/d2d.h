// Device-to-device (D2D) frames for the cooperative fallback (v0.9), sent with ESP-NOW broadcast.
// Same idea as V2V for cars in a tunnel: devices keep telling each other where they are when the
// network is gone, and a device that still hears the MEC app relays for one that does not.
//   STATE     every report tick: who I am, where I am, my velocity, whether I still hear MEC
//   ALERT     a MEC alert re-broadcast for a device that reported mecOk = 0 (one hop, never re-relayed)
//   HEARTBEAT the MEC heartbeat re-broadcast the same way
// In a 5G deployment the same frames map onto sidelink (PC5); nothing here is ESP-NOW specific.
#pragma once
#include <stdint.h>
#include <string.h>
#include <stddef.h>

namespace d2d {

enum : uint8_t { STATE = 1, ALERT = 2, HEARTBEAT = 3 };
enum : uint8_t { WORKER = 0, FORKLIFT = 1 };
const uint8_t VERSION = 1;
const float NEIGHBOUR_OFFLINE_S = 1.0f;   // relay for a neighbour that said mecOk=0 this recently
const int RELAY_REPEAT = 3;               // relayed frames go out 3x: with 60 % frame loss a lossy relay
                                          // was worse than none (sim/d2d_sensitivity.py)

#pragma pack(push, 1)
struct Frame {
  uint8_t version = VERSION;
  uint8_t type = STATE;
  char id[12] = {0};          // STATE: sender id; ALERT: destination id
  uint16_t shortAddr = 0;     // UWB short address of the sender (ties D2D to the ranging peer)
  uint8_t kind = WORKER;
  uint8_t mecOk = 1;
  float x = 0, y = 0, vx = 0, vy = 0;
  uint8_t clear = 0, vibrate = 0, beacon = 0, level = 0;   // ALERT
  float limit = -1.0f;                                     // ALERT: m/s, -1 = none
  char src[12] = {0};         // who sent this frame (ALERT / HEARTBEAT: the relayer)
  uint32_t seq = 0;           // sender clock, 100 ms units (d2d_auth.h)
  uint8_t tag[8] = {0};       // HMAC-SHA256(site key, bytes before tag)[0..7] (d2d_auth.h)
};
#pragma pack(pop)
static_assert(sizeof(Frame) <= 250, "ESP-NOW payload limit");

inline void setId(Frame& f, const char* s) { strncpy(f.id, s, sizeof(f.id) - 1); f.id[sizeof(f.id) - 1] = 0; }
inline bool idIs(const Frame& f, const char* s) { return strncmp(f.id, s, sizeof(f.id)) == 0; }
// Neighbours that recently said they cannot hear the MEC app (who to relay for).
struct Neighbours {
  static const int N = 8;
  char id[N][12];
  uint8_t kind[N];
  float offlineAt[N];
  int n = 0;
  void seen(const Frame& f, float t) {
    int k = -1;
    for (int i = 0; i < n; i++) if (strncmp(id[i], f.id, 12) == 0) k = i;
    if (k < 0) { if (n == N) return; k = n++; memcpy(id[k], f.id, 12); offlineAt[k] = -1e9f; }
    kind[k] = f.kind;
    if (!f.mecOk) offlineAt[k] = t;
  }
  bool offline(const char* who, float t) const {
    for (int i = 0; i < n; i++) if (strncmp(id[i], who, 12) == 0) return t - offlineAt[i] <= NEIGHBOUR_OFFLINE_S;
    return false;
  }
  bool anyOffline(float t) const {
    for (int i = 0; i < n; i++) if (t - offlineAt[i] <= NEIGHBOUR_OFFLINE_S) return true;
    return false;
  }
};

// ESP-NOW receive callbacks run in the Wi-Fi task: copy frames here, handle them in loop().
struct Inbox {
  static const int N = 8;
  Frame q[N];
  volatile int head = 0, tail = 0;
  void push(const uint8_t* data) { int h = (head + 1) % N; if (h == tail) return; memcpy(&q[head], data, sizeof(Frame)); head = h; }
  bool pop(Frame& f) { if (tail == head) return false; f = q[tail]; tail = (tail + 1) % N; return true; }
};

inline bool valid(const uint8_t* data, int len) { return len == (int)sizeof(Frame) && data[0] == VERSION; }

}  // namespace d2d
