// EdgeGuard worker tag WAIT / GO cue - C++ mirror of edgeguard/worker_cue.py (cross-tested).
// raise/refresh+vibrate -> WAIT (burst, red LED, 1 s pulses); raise/refresh/wait keep it;
// aside -> STEP ASIDE (long burst) then WAIT; clear/release -> GO (two short pulses); nothing heard for HOLD_IDLE_S -> GO by itself.
// One hold per forklift (key = forklift id): a clear from one forklift keeps the WAIT of another.
#pragma once
#include <cmath>
#include <cstring>

namespace cue {

constexpr float HOLD_MAX_S = 20.0f;   // longest WAIT kept through MEC silence while a truck is near (D2D)
constexpr float HOLD_IDLE_S = 2.5f, PULSE_PERIOD_S = 1.0f, PULSE_ON_S = 0.15f;
constexpr int MAX_HOLDS = 4;

struct WaitCue {
  struct Hold { char key[16]; float until; bool used; };
  Hold holds[MAX_HOLDS] = {};
  float since = 0, burstUntil = 0, goAt = -1;

  int find(const char* key) const {
    for (int i = 0; i < MAX_HOLDS; i++) if (holds[i].used && !strcmp(holds[i].key, key)) return i;
    return -1;
  }
  int count() const { int n = 0; for (const Hold& h : holds) n += h.used; return n; }
  bool waiting() const { return count() > 0; }
  void drop(float t, int i) {
    holds[i].used = false;
    if (count() == 0) goAt = t;
  }
  // walkBlock: the tag's GO check says walking on now meets a truck - a clear / release only shortens the WAIT
  void onAlert(float t, const char* ev, bool vibrate, bool danger, const char* src = "", bool walkBlock = false) {
    const char* key = src;
    tick(t);
    if (!strcmp(ev, "aside")) { ev = "raise"; vibrate = true; danger = true; }   // step aside, then WAIT
    int i = find(key);
    if (!strcmp(ev, "clear") || !strcmp(ev, "release")) {
      if (i >= 0) { if (walkBlock && t - since < HOLD_MAX_S) holds[i].until = t + 0.2f; else drop(t, i); }
      return;
    }
    if (strcmp(ev, "raise") && strcmp(ev, "refresh") && strcmp(ev, "wait")) return;
    if (i >= 0) {
      holds[i].until = t + HOLD_IDLE_S;
      if (vibrate && !strcmp(ev, "raise")) burstUntil = t + (danger ? 1.5f : 0.6f);
    } else if (vibrate && count() < MAX_HOLDS) {
      if (count() == 0) { since = t; goAt = -1; }
      for (Hold& h : holds) if (!h.used) {
        h.used = true; h.until = t + HOLD_IDLE_S;
        strncpy(h.key, key, sizeof h.key - 1); h.key[sizeof h.key - 1] = 0;
        break;
      }
      burstUntil = t + (danger ? 1.5f : 0.6f);
    }
  }
  // keep: the tag's D2D rule sees a truck close - a hold that heard nothing is kept (up to HOLD_MAX_S)
  void tick(float t, bool keep = false) {
    for (int i = 0; i < MAX_HOLDS; i++) if (holds[i].used && t >= holds[i].until) {
      if (keep && t - since < HOLD_MAX_S) holds[i].until = t + 0.2f; else drop(t, i);
    }
  }
  bool led(float t, bool keep = false) { tick(t, keep); return waiting(); }
  bool motor(float t, bool keep = false) {
    tick(t, keep);
    if (t < burstUntil) return true;
    if (waiting()) return std::fmod(t - since, PULSE_PERIOD_S) < PULSE_ON_S;
    if (goAt >= 0) { float d = t - goAt; return (d >= 0 && d < 0.08f) || (d >= 0.16f && d < 0.24f); }
    return false;
  }
};

}  // namespace cue
