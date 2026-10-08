"""Device-side rules for alerts and rate commands (reference for the firmware and the sims).

Forklift speed limit, fail-safe on silence:
  * an active limit is refreshed by the MEC app every 1 s (0.5 s on a congested cell) and
    held as the last plan between refreshes;
  * the MEC app also sends a heartbeat on <ae>/control every 1 s, written at lower priority
    than alerts (so a heartbeat that arrives proves no alert is queued behind it);
  * MEC heard, but no refresh for this pair for ALERT_STALE_S -> the pair cleared and the
    "clear" was lost: lift the limit;
  * nothing at all from the MEC app for SILENCE_S -> it is restarting or unreachable: keep
    holding the last limit (a restart takes ~2 s);
  * silence longer than STOP_AFTER_S -> the MEC app is really down: a forklift that is
    under an active limit stops until the MEC app is heard again.  Silence never lifts a limit.

Chosen by sim/failsafe_eval.py (results/failsafe_eval.json): during a short outage, crawling
or stopping caused *more* collisions than holding the plan (the plan deliberately lets a
truck clear a crossing or stop short of it; a crawling truck stays in the conflict zone),
and lifting a stale limit after 2.2 s instead of 5 s did too.  When the MEC app stays down,
stopping is clearly better (8 s outage: 60 vs 93 collisions of 180).  Stopping after 2.0 s of
silence is never worse than v0.6 and better in every outage (of 180 conflicts: restart 27 vs
30, restart + 20 % loss 42 vs 43, 8 s outage 78 vs 93; normal 19 = 19).  v0.6 ("legacy")
lifted the limit after 5 s even when the MEC app was dead.

Local UWB fallback (modes "failsafe_local_zone" / "failsafe_local_ttc", v0.8):
  holding the plan only protects pairs the MEC app had already flagged; a worker who appears
  while the MEC app is silent is unprotected.  The forklift module therefore ranges the worker
  tags directly (the same DW1000 two-way ranging it does with the anchors, peer to peer) and,
  only while the MEC app is silent, applies a local rule on top of the held plan:
    zone : distance < LOCAL_STOP_M -> stop, < LOCAL_SLOW_M -> LOCAL_SLOW_MPS
    ttc  : the same zones, plus range-rate: closing and distance / closing speed below
           LOCAL_TTC_STOP_S -> stop, below LOCAL_TTC_SLOW_S -> LOCAL_SLOW_MPS
  "halt_on_silence" (reference, not used): every forklift stops after 2 s of silence.
  "failsafe_local_ttc_tag" also vibrates the worker's tag from the same ranging (two-way
  ranging gives both ends the distance), so the worker stops too.
  With the local guard the 2 s "stop under an active limit" still applies.  While the MEC app
  is heard, the local rule is off (the MEC prediction has far fewer false alarms).

Cooperative D2D fallback (mode "coop", v0.9) - the "cars in a tunnel" idea:
  every device broadcasts its own state peer to peer (ESP-NOW on the ESP32; 5G sidelink / PC5
  in a real deployment): worker tag {x, y, vx, vy} from its UWB fix, forklift {x, y, vx, vy}
  from its tag board and drive.  Positions keep coming because the UWB anchors do not depend on
  the network.  Two uses:
    1. local 2-D prediction while the MEC app is silent: closest point of approach under
       constant velocity (d_min at t_cpa) instead of range + range-rate - a worker walking past
       is no longer a reason to stop.  stop: now < LOCAL_STOP_M, or t_cpa < CPA_STOP_S with
       d_min < CPA_STOP_D_M; slow (LOCAL_SLOW_MPS): t_cpa < CPA_SLOW_S with d_min < CPA_SLOW_D_M.
       A peer whose state is older than D2D_STALE_S falls back to the v0.8 range rule.
    2. relay for dead zones (metal racks): a device that still hears the MEC app forwards MEC
       alerts / heartbeats to neighbours that do not, and forwards their state up to the MEC
       app (sim/closed_loop.py).  A device in a dead zone then behaves as if it were connected.

Reporting rate: follow the commanded rate; without any command for RATE_FAILSAFE_S fall
back to the full rate.

firmware/forklift_module and firmware/worker_tag implement the same rules.
"""
from __future__ import annotations

ALERT_STALE_S = 5.0      # same timing as v0.6 (the trained policy assumes it)
SILENCE_S = 1.3          # heartbeat (1 s) and alert refresh (1 s) both missing
STOP_AFTER_S = 2.0       # swept 1.3-3.0 s (results/failsafe_stop_sweep.json): best overall
CREEP_MPS = 0.5          # crawl speed (evaluated variant "failsafe_creep", not used)
RATE_FAILSAFE_S = 6.0
LOCAL_SLOW_M = 6.0       # local fallback zones (direct UWB ranging forklift <-> worker tag)
LOCAL_STOP_M = 3.0
LOCAL_SLOW_MPS = 1.0
LOCAL_TTC_SLOW_S = 4.0
LOCAL_TTC_STOP_S = 2.0
D2D_STALE_S = 0.5        # peer state older than this -> range rule for that peer
CPA_HORIZON_S = 5.0
CPA_STOP_S, CPA_STOP_D_M = 2.5, 2.0
CPA_SLOW_S, CPA_SLOW_D_M = 4.5, 3.0
LOCAL_AFTER_S = STOP_AFTER_S   # swept 1.3 / 2.0 / 3.0 s: 2.0 best overall (results/failsafe_eval.json)
LOCAL_RANGE_STALE_S = 1.2   # no range for this long -> the tag is out of reach, rule idle
LOCAL_RATE_WINDOW_S = 1.5   # range-rate fit window; 1.2 / 1.5 s keep 2 Hz ranging usable (results/peer_ranging_sensitivity.json)
FULL_HZ = 10.0


class ForkliftLimit:
    """mode "coop" (default, v0.9), "failsafe_local_ttc_tag" (v0.8), "failsafe" (v0.7, above), "legacy" (v0.6: lift after 5 s even when the MEC app
    is silent) or the rejected variants "failsafe_creep" / "failsafe_stop"."""
    MODE = "coop"     # v0.9; without D2D frames it behaves as v0.8, without direct ranges as v0.7

    def __init__(self, mode=None):
        self.mode = mode or ForkliftLimit.MODE
        self.limit, self.limit_t, self.hb_t = None, -1e9, -1e9
        self.ranges = {}                               # tag -> [(t, d)] recent direct ranges
        self.own = None                                # (t, x, y, vx, vy) this device (coop)
        self.peers = {}                                # tag -> (t, x, y, vx, vy) via D2D

    def on_own_state(self, t, x, y, vx, vy):
        self.own = (t, x, y, vx, vy)

    def on_peer_state(self, t, tag, x, y, vx, vy):
        """D2D broadcast received from a neighbour (coop mode)."""
        self.peers[tag] = (t, x, y, vx, vy)

    def _cpa_cap(self, t, tag):
        """Speed cap from the 2-D closest point of approach with this peer, or "stale"."""
        p = self.peers.get(tag)
        if self.own is None or p is None or t - p[0] > D2D_STALE_S or t - self.own[0] > D2D_STALE_S:
            return "stale"
        rx, ry = p[1] - self.own[1], p[2] - self.own[2]
        wx, wy = p[3] - self.own[3], p[4] - self.own[4]
        d_now = (rx * rx + ry * ry) ** 0.5
        if d_now < LOCAL_STOP_M:
            return 0.0
        ww = wx * wx + wy * wy
        t_cpa = 0.0 if ww < 1e-9 else max(0.0, -(rx * wx + ry * wy) / ww)
        if t_cpa > CPA_HORIZON_S:
            return None
        cx, cy = rx + wx * t_cpa, ry + wy * t_cpa
        d_min = (cx * cx + cy * cy) ** 0.5
        if t_cpa < CPA_STOP_S and d_min < CPA_STOP_D_M:
            return 0.0
        if t_cpa < CPA_SLOW_S and d_min < CPA_SLOW_D_M:
            return LOCAL_SLOW_MPS
        return None

    def on_range(self, t, tag, d):
        """Direct UWB range to a worker tag (local fallback; ignored by the other modes)."""
        h = self.ranges.setdefault(tag, [])
        h.append((t, d))
        while h and t - h[0][0] > LOCAL_RATE_WINDOW_S:
            h.pop(0)

    def local_limit(self, t):
        """Speed cap from direct ranging, or None (no tag close / not a local mode)."""
        if not (self.mode.startswith("failsafe_local") or self.mode.startswith("coop")):
            return None
        cap = None
        for tag in set(self.ranges) | set(self.peers):
            if self.mode.startswith("coop"):
                c = self._cpa_cap(t, tag)
                if c != "stale":
                    if c is not None:
                        cap = c if cap is None else min(cap, c)
                    continue
            h = self.ranges.get(tag)
            if not h or t - h[-1][0] > LOCAL_RANGE_STALE_S:
                continue
            d = h[-1][1]
            c = None
            if d < LOCAL_STOP_M:
                c = 0.0
            elif d < LOCAL_SLOW_M:
                c = LOCAL_SLOW_MPS
            if ("ttc" in self.mode or self.mode.startswith("coop")) and len(h) >= 3 and h[-1][0] - h[0][0] > 0.2:
                n = len(h)
                mt = sum(x for x, _ in h) / n
                md = sum(y for _, y in h) / n
                den = sum((x - mt) ** 2 for x, _ in h)
                rate = sum((x - mt) * (y - md) for x, y in h) / den if den else 0.0
                if rate < -0.2:                          # closing faster than 0.2 m/s
                    ttc = d / -rate
                    if ttc < LOCAL_TTC_STOP_S:
                        c = 0.0
                    elif ttc < LOCAL_TTC_SLOW_S:
                        c = LOCAL_SLOW_MPS if c is None else min(c, LOCAL_SLOW_MPS)
            if c is not None:
                cap = c if cap is None else min(cap, c)
        return cap

    def on_alert(self, t, event, limit):
        self.hb_t = t                                  # any MEC message proves it is alive
        self.limit, self.limit_t = (None if event == "clear" else limit), t

    def on_heartbeat(self, t):
        self.hb_t = t

    def mec_silent(self, t):
        return t - self.hb_t > LOCAL_AFTER_S

    def vibrate_local(self, t):
        """Worker-tag side of the local fallback: vibrate when the rule says stop."""
        return self.local_mode() and self.mec_silent(t) and self.local_limit(t) == 0.0

    def local_mode(self):
        return self.mode.startswith("failsafe_local") or self.mode.startswith("coop")

    def effective(self, t):
        if self.mode == "halt_on_silence" and t - self.hb_t > STOP_AFTER_S:
            return 0.0                                 # reference only: every truck stops
        held = self._held(t)
        if self.local_mode() and t - self.hb_t > LOCAL_AFTER_S:
            loc = self.local_limit(t)
            if loc is not None:
                return loc if held is None else min(held, loc)
        return held

    def _held(self, t):
        if self.limit is None:
            return None
        if self.mode == "legacy":
            if t - self.limit_t > 5.0:
                self.limit = None
            return self.limit
        if t - self.hb_t > SILENCE_S:                  # MEC silent
            if self.mode == "failsafe_creep":
                return min(self.limit, CREEP_MPS)
            if self.mode == "failsafe_stop" or ((self.mode.startswith("failsafe") or self.mode.startswith("coop"))
                                                and self.mode != "failsafe_creep" and t - self.hb_t > STOP_AFTER_S):
                return 0.0
            return self.limit                          # hold the last plan (MEC restarting)
        if t - self.limit_t > ALERT_STALE_S:           # MEC alive, refreshes stopped: clear lost
            self.limit = None
        return self.limit


class ReportRate:
    def __init__(self):
        self.hz, self.t = FULL_HZ, -1e9

    def on_command(self, t, hz):
        self.hz, self.t = hz, t

    def current(self, t):
        return self.hz if t - self.t <= RATE_FAILSAFE_S else FULL_HZ
