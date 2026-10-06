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
stopping is clearly better (8 s outage: 60 vs 93 collisions of 180).  v0.6 ("legacy")
lifted the limit after 5 s even when the MEC app was dead.

Reporting rate: follow the commanded rate; without any command for RATE_FAILSAFE_S fall
back to the full rate.

firmware/forklift_module and firmware/worker_tag implement the same rules.
"""
from __future__ import annotations

ALERT_STALE_S = 5.0      # same timing as v0.6 (the trained policy assumes it)
SILENCE_S = 1.3          # heartbeat (1 s) and alert refresh (1 s) both missing
STOP_AFTER_S = 3.0       # longer than a MEC app restart (measured 1.4-2.2 s)
CREEP_MPS = 0.5          # crawl speed (evaluated variant "failsafe_creep", not used)
RATE_FAILSAFE_S = 6.0
FULL_HZ = 10.0


class ForkliftLimit:
    """mode "failsafe" (default, above), "legacy" (v0.6: lift after 5 s even when the MEC app
    is silent) or the rejected variants "failsafe_creep" / "failsafe_stop"."""
    MODE = "failsafe"

    def __init__(self, mode=None):
        self.mode = mode or ForkliftLimit.MODE
        self.limit, self.limit_t, self.hb_t = None, -1e9, -1e9

    def on_alert(self, t, event, limit):
        self.hb_t = t                                  # any MEC message proves it is alive
        self.limit, self.limit_t = (None if event == "clear" else limit), t

    def on_heartbeat(self, t):
        self.hb_t = t

    def effective(self, t):
        if self.limit is None:
            return None
        if self.mode == "legacy":
            if t - self.limit_t > 5.0:
                self.limit = None
            return self.limit
        if t - self.hb_t > SILENCE_S:                  # MEC silent
            if self.mode == "failsafe_creep":
                return min(self.limit, CREEP_MPS)
            if self.mode == "failsafe_stop" or (self.mode == "failsafe" and t - self.hb_t > STOP_AFTER_S):
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
