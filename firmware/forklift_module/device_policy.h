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
// Local UWB fallback (v0.8, localTtc = true): while the MEC app is silent for LOCAL_AFTER_S,
//   direct DW1000 ranging to worker tags caps the speed: distance < 3 m or closing with
//   time-to-collision < 2 s -> stop; < 6 m or TTC < 4 s -> 1 m/s.  The worker tag runs the same
//   rule on the same two-way range and vibrates on "stop" (vibrateLocal).  Off while MEC is heard.
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
const double LOCAL_SLOW_M = 6.0, LOCAL_STOP_M = 3.0, LOCAL_SLOW_MPS = 1.0;
const double LOCAL_TTC_SLOW_S = 4.0, LOCAL_TTC_STOP_S = 2.0;
const double LOCAL_AFTER_S = STOP_AFTER_S, LOCAL_RANGE_STALE_S = 1.2, LOCAL_RATE_WINDOW_S = 1.5;
const int LOCAL_TAGS = 8, LOCAL_HIST = 24;   // 1.5 s at 10 Hz + margin

// Recent direct ranges per worker tag, and the speed cap they imply (mirrors local_limit()).
struct LocalGuard {
  int ids[LOCAL_TAGS];
  double ht[LOCAL_TAGS][LOCAL_HIST], hd[LOCAL_TAGS][LOCAL_HIST];
  int n[LOCAL_TAGS];
  int used = 0;
  LocalGuard() { for (int i = 0; i < LOCAL_TAGS; i++) { ids[i] = -1; n[i] = 0; } }

  void onRange(double t, int tag, double d) {
    int k = -1;
    for (int i = 0; i < used; i++) if (ids[i] == tag) k = i;
    if (k < 0) { if (used == LOCAL_TAGS) return; k = used++; ids[k] = tag; n[k] = 0; }
    if (n[k] == LOCAL_HIST) { shift(k); }
    ht[k][n[k]] = t; hd[k][n[k]] = d; n[k]++;
    while (n[k] > 0 && t - ht[k][0] > LOCAL_RATE_WINDOW_S) shift(k);
  }
  void shift(int k) { for (int j = 1; j < n[k]; j++) { ht[k][j - 1] = ht[k][j]; hd[k][j - 1] = hd[k][j]; } n[k]--; }

  // speed cap in m/s from direct ranging, or NO_LIMIT
  double cap(double t, bool ttc) const {
    double c0 = NO_LIMIT;
    for (int k = 0; k < used; k++) {
      int m = n[k];
      if (m == 0 || t - ht[k][m - 1] > LOCAL_RANGE_STALE_S) continue;
      double d = hd[k][m - 1], c = NO_LIMIT;
      if (d < LOCAL_STOP_M) c = 0.0;
      else if (d < LOCAL_SLOW_M) c = LOCAL_SLOW_MPS;
      if (ttc && m >= 3 && ht[k][m - 1] - ht[k][0] > 0.2) {
        double st = 0, sd = 0;
        for (int j = 0; j < m; j++) { st += ht[k][j]; sd += hd[k][j]; }
        double mt = st / m, md = sd / m, den = 0, num = 0;
        for (int j = 0; j < m; j++) den += (ht[k][j] - mt) * (ht[k][j] - mt);
        for (int j = 0; j < m; j++) num += (ht[k][j] - mt) * (hd[k][j] - md);
        double rate = den != 0 ? num / den : 0.0;
        if (rate < -0.2) {
          double tc = d / -rate;
          if (tc < LOCAL_TTC_STOP_S) c = 0.0;
          else if (tc < LOCAL_TTC_SLOW_S) c = (c < 0) ? LOCAL_SLOW_MPS : (c < LOCAL_SLOW_MPS ? c : LOCAL_SLOW_MPS);
        }
      }
      if (c >= 0) c0 = (c0 < 0 || c < c0) ? c : c0;
    }
    return c0;
  }
};

struct ForkliftLimit {
  float limit = NO_LIMIT;
  float limitT = -1e9f;
  float hbT = -1e9f;
  bool localTtc = true;                  // v0.8 local UWB fallback (no ranges -> v0.7 behaviour)
  LocalGuard local;

  void onRange(double t, int tag, double d) { local.onRange(t, tag, d); }
  bool mecSilent(double t) const { return t - hbT > LOCAL_AFTER_S; }
  // worker tag side: vibrate when the local rule says stop
  bool vibrateLocal(double t) const { return localTtc && mecSilent(t) && local.cap(t, true) == 0.0; }

  // event: 0 = raise / refresh, 1 = clear
  void onAlert(float t, bool clear, float lim) {
    hbT = t;                             // any MEC message proves it is alive
    limit = clear ? NO_LIMIT : lim;
    limitT = t;
  }
  void onHeartbeat(float t) { hbT = t; }

  // effective limit in m/s, or NO_LIMIT
  float effective(float t) {
    float held = heldLimit(t);
    if (localTtc && mecSilent(t)) {
      double c = local.cap(t, true);
      if (c >= 0) return (held < 0 || (float)c < held) ? (float)c : held;
    }
    return held;
  }

  float heldLimit(float t) {
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
