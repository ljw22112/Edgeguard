// Device-side rules for alerts and rate commands - same logic as edgeguard/device_policy.py
// (tests/test_device_policy.py runs random event sequences through both and compares).
//
// Forklift speed limit, fail-safe on silence:
//   - an active limit is held as the last plan between refreshes (MEC refreshes every 1 s);
//   - MEC heard (heartbeat on <ae>/control every 1 s) but no refresh for ALERT_STALE_S
//     -> the "clear" was lost: lift the limit;
//   - nothing from the MEC app for SILENCE_S -> it is restarting: keep holding;
//   - silence longer than STOP_AFTER_S -> it is down: stop (limit 0) until heard again.
//     Silence never lifts a limit.
// Reporting rate: follow the commanded rate; no command for RATE_FAILSAFE_S -> full rate.
//
// Times are seconds on the device's own monotonic clock (millis() / 1000).
#pragma once

namespace policy {

const float ALERT_STALE_S = 5.0f;
const float SILENCE_S = 1.3f;
const float STOP_AFTER_S = 2.0f;
const float RATE_FAILSAFE_S = 6.0f;
const float FULL_HZ = 10.0f;
const float NO_LIMIT = -1.0f;            // "no limit" (a limit is always >= 0)

struct ForkliftLimit {
  float limit = NO_LIMIT;
  float limitT = -1e9f;
  float hbT = -1e9f;

  // event: 0 = raise / refresh, 1 = clear
  void onAlert(float t, bool clear, float lim) {
    hbT = t;                             // any MEC message proves it is alive
    limit = clear ? NO_LIMIT : lim;
    limitT = t;
  }
  void onHeartbeat(float t) { hbT = t; }

  // effective limit in m/s, or NO_LIMIT
  float effective(float t) {
    if (limit < 0) return NO_LIMIT;
    if (t - hbT > SILENCE_S) {           // MEC silent
      if (t - hbT > STOP_AFTER_S) return 0.0f;
      return limit;                      // restarting: hold the last plan
    }
    if (t - limitT > ALERT_STALE_S) limit = NO_LIMIT;   // MEC alive, clear lost
    return limit;
  }
};

struct ReportRate {
  float hz = FULL_HZ;
  float t = -1e9f;
  void onCommand(float now, float rateHz) {
    if (rateHz > 0) { hz = rateHz; t = now; }
  }
  float current(float now) const { return now - t <= RATE_FAILSAFE_S ? hz : FULL_HZ; }
  unsigned long periodMs(float now) const { return (unsigned long)(1000.0f / current(now) + 0.5f); }
};

}  // namespace policy
