// EdgeGuard worker tag WAIT / GO cue - C++ mirror of edgeguard/worker_cue.py (cross-tested).
// raise/refresh+vibrate -> WAIT (burst, red LED, 1 s pulses); raise/refresh/wait keep it;
// clear/release -> GO (two short pulses); nothing heard for HOLD_IDLE_S -> GO by itself.
#pragma once
#include <cmath>
#include <cstring>

namespace cue {

constexpr float HOLD_IDLE_S = 2.5f, PULSE_PERIOD_S = 1.0f, PULSE_ON_S = 0.15f;

struct WaitCue {
  bool waiting = false;
  float until = 0, since = 0, burstUntil = 0, goAt = -1;

  void onAlert(float t, const char* ev, bool vibrate, bool danger) {
    if (!strcmp(ev, "clear") || !strcmp(ev, "release")) {
      if (waiting) { waiting = false; goAt = t; }
      return;
    }
    if (strcmp(ev, "raise") && strcmp(ev, "refresh") && strcmp(ev, "wait")) return;
    if (waiting && t < until) {
      until = t + HOLD_IDLE_S;
      if (vibrate && !strcmp(ev, "raise")) burstUntil = t + (danger ? 1.5f : 0.6f);
    } else if (vibrate) {
      waiting = true; since = t; until = t + HOLD_IDLE_S;
      burstUntil = t + (danger ? 1.5f : 0.6f); goAt = -1;
    }
  }
  void tick(float t) { if (waiting && t >= until) { waiting = false; goAt = t; } }
  bool led(float t) { tick(t); return waiting; }
  bool motor(float t) {
    tick(t);
    if (t < burstUntil) return true;
    if (waiting) return std::fmod(t - since, PULSE_PERIOD_S) < PULSE_ON_S;
    if (goAt >= 0) { float d = t - goAt; return (d >= 0 && d < 0.08f) || (d >= 0.16f && d < 0.24f); }
    return false;
  }
};

}  // namespace cue
