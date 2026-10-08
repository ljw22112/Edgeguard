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
// Cooperative D2D (v0.9, coop = true): devices broadcast {x, y, vx, vy} peer to peer (ESP-NOW, d2d.h).
//   While the MEC app is silent, a peer with fresh state (< D2D_STALE_S) is judged by the 2-D closest
//   point of approach (constant velocity) instead of range + range-rate; stale peers keep the range rule.
// Reporting rate: follow the commanded rate; no command for RATE_FAILSAFE_S -> full rate.
//
// Times are seconds on the device's own monotonic clock (millis() / 1000).
#pragma once
#include <cmath>

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
const double D2D_STALE_S = 0.5, CPA_HORIZON_S = 5.0;
const double CPA_STOP_S = 2.5, CPA_STOP_D_M = 2.0, CPA_SLOW_S = 4.5, CPA_SLOW_D_M = 3.0;
const double CPA_STALE = -2.0;            // "no fresh D2D state for this peer"

// 2-D closest point of approach between this device (own) and a peer, both constant velocity.
// Returns a speed cap, NO_LIMIT, or CPA_STALE (mirrors ForkliftLimit._cpa_cap()).
inline double cpaCap(double t, const double own[5], const double peer[5]) {
  if (own[0] < -1e8 || peer[0] < -1e8 || t - peer[0] > D2D_STALE_S || t - own[0] > D2D_STALE_S) return CPA_STALE;
  double rx = peer[1] - own[1], ry = peer[2] - own[2];
  double wx = peer[3] - own[3], wy = peer[4] - own[4];
  double dNow = std::sqrt(rx * rx + ry * ry);
  if (dNow < LOCAL_STOP_M) return 0.0;
  double ww = wx * wx + wy * wy;
  double tc = ww < 1e-9 ? 0.0 : -(rx * wx + ry * wy) / ww;
  if (tc < 0.0) tc = 0.0;
  if (tc > CPA_HORIZON_S) return NO_LIMIT;
  double cx = rx + wx * tc, cy = ry + wy * tc;
  double dMin = std::sqrt(cx * cx + cy * cy);
  if (tc < CPA_STOP_S && dMin < CPA_STOP_D_M) return 0.0;
  if (tc < CPA_SLOW_S && dMin < CPA_SLOW_D_M) return LOCAL_SLOW_MPS;
  return NO_LIMIT;
}

// Recent direct ranges per worker tag, and the speed cap they imply (mirrors local_limit()).
struct LocalGuard {
  int ids[LOCAL_TAGS];
  double ht[LOCAL_TAGS][LOCAL_HIST], hd[LOCAL_TAGS][LOCAL_HIST];
  int n[LOCAL_TAGS];
  int used = 0;
  double own[5] = {-1e9, 0, 0, 0, 0};
  double peer[LOCAL_TAGS][5];
  LocalGuard() { for (int i = 0; i < LOCAL_TAGS; i++) { ids[i] = -1; n[i] = 0; peer[i][0] = -1e9; } }

  int slot(int tag) {
    for (int i = 0; i < used; i++) if (ids[i] == tag) return i;
    if (used == LOCAL_TAGS) return -1;
    ids[used] = tag; n[used] = 0; peer[used][0] = -1e9;
    return used++;
  }
  void onOwnState(double t, double x, double y, double vx, double vy) { own[0] = t; own[1] = x; own[2] = y; own[3] = vx; own[4] = vy; }
  void onPeerState(double t, int tag, double x, double y, double vx, double vy) {
    int k = slot(tag);
    if (k < 0) return;
    peer[k][0] = t; peer[k][1] = x; peer[k][2] = y; peer[k][3] = vx; peer[k][4] = vy;
  }

  void onRange(double t, int tag, double d) {
    int k = slot(tag);
    if (k < 0) return;
    if (n[k] == LOCAL_HIST) { shift(k); }
    ht[k][n[k]] = t; hd[k][n[k]] = d; n[k]++;
    while (n[k] > 0 && t - ht[k][0] > LOCAL_RATE_WINDOW_S) shift(k);
  }
  void shift(int k) { for (int j = 1; j < n[k]; j++) { ht[k][j - 1] = ht[k][j]; hd[k][j - 1] = hd[k][j]; } n[k]--; }

  // speed cap in m/s from direct ranging, or NO_LIMIT
  double cap(double t, bool ttc, bool coop = false) const {
    double c0 = NO_LIMIT;
    for (int k = 0; k < used; k++) {
      if (coop) {
        double cc = cpaCap(t, own, peer[k]);
        if (cc != CPA_STALE) {
          if (cc >= 0) c0 = (c0 < 0 || cc < c0) ? cc : c0;
          continue;
        }
      }
      int m = n[k];
      if (m == 0 || t - ht[k][m - 1] > LOCAL_RANGE_STALE_S) continue;
      double d = hd[k][m - 1], c = NO_LIMIT;
      if (d < LOCAL_STOP_M) c = 0.0;
      else if (d < LOCAL_SLOW_M) c = LOCAL_SLOW_MPS;
      if ((ttc || coop) && m >= 3 && ht[k][m - 1] - ht[k][0] > 0.2) {
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
  bool coop = true;                      // v0.9 D2D state -> 2-D closest approach (no D2D -> v0.8)
  LocalGuard local;

  void onRange(double t, int tag, double d) { local.onRange(t, tag, d); }
  void onOwnState(double t, double x, double y, double vx, double vy) { local.onOwnState(t, x, y, vx, vy); }
  void onPeerState(double t, int tag, double x, double y, double vx, double vy) { local.onPeerState(t, tag, x, y, vx, vy); }
  bool mecSilent(double t) const { return t - hbT > LOCAL_AFTER_S; }
  // worker tag side: vibrate when the local rule says stop
  bool vibrateLocal(double t) const { return localTtc && mecSilent(t) && local.cap(t, true, coop) == 0.0; }

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
      double c = local.cap(t, true, coop);
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
