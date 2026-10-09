"""Alert policy: turns per-pair risk assessments into alert events and device actions.

Shared by the MEC app and the simulators, so what is trained and evaluated in
simulation is exactly what runs on the MEC host.
"""
from __future__ import annotations

from .risk import LEVELS, go_safe, waiting_at_lane


NOMINAL_DT = 0.1      # s: the debounce count is tuned for 10 Hz tag data
STALE_RESET_S = 2.0   # s without an evaluation (tracks went stale): the encounter is over


class AlertState:
    """Edge-triggered alerts with debounce and hold, per worker/forklift pair.

    The debounce is a time window (debounce x 0.1 s at the nominal 10 Hz).  When samples
    are sparser than that window - e.g. ~1 Hz network positions from the MEC Location API -
    one evaluation already spans it, so it counts in full instead of costing an extra
    sample period of warning time (measured on the MEC Sandbox path: 62 % -> see docs/mec-sandbox.md)."""

    def __init__(self, debounce=2, refresh_s=1.0, hold_s=2.0):
        self.level, self.streak, self.last_sent, self.below_since = 0, 0, 0.0, None
        self.debounce, self.refresh_s, self.hold_s = debounce, refresh_s, hold_s
        self.sent_limit = None
        self.last_eval = None
        self.released = False             # worker already told GO in this encounter
        self.intent = None                # worker velocity while walking during the alert (where he wants to go)
        self.last_any = 0.0               # last message of any kind for this pair (WAIT keep-alive)

    def reset(self):
        self.level, self.streak, self.below_since, self.sent_limit, self.last_eval = 0, 0, None, None, None
        self.released, self.intent = False, None

    def step(self, level, now):
        """Return 'raise', 'refresh', 'clear' or None."""
        if self.last_eval is not None and now - self.last_eval > STALE_RESET_S:
            # The pair was not evaluated for a while (one of them left or went silent), so the
            # previous encounter is over.  Without this, an alert state left at WARNING turned the
            # next encounter's first alert into a "refresh", which may not vibrate the tag.
            self.reset()
        gap = None if self.last_eval is None else now - self.last_eval
        self.last_eval = now
        if level >= 2:
            self.below_since = None
            self.streak += 1
            sparse = gap is not None and gap >= self.debounce * NOMINAL_DT - 1e-9
            fire = level == 3 or self.streak >= self.debounce or sparse
            if fire and level > self.level:
                self.level, self.last_sent = level, now
                return "raise"
            if fire and now - self.last_sent >= self.refresh_s:
                self.level, self.last_sent = level, now        # may step down DANGER -> WARNING
                return "refresh"
            return None
        self.streak = 0
        if self.level >= 2:
            self.below_since = self.below_since or now
            if now - self.below_since >= self.hold_s:
                self.level, self.below_since = level, None
                return "clear"
        else:
            self.level = level
        return None


def decide(st: AlertState, r, w_tr, f_tr, cfg, now, congested=False):
    """Update the pair's alert state with assessment `r`.

    Returns (event or None, actions dict).  May modify `r` (hold logic)."""
    st.refresh_s = 0.5 if congested else 1.0
    st.debounce, st.hold_s = cfg.debounce, cfg.clear_hold
    if getattr(r, "occluded", False) and getattr(cfg, "occl_debounce", 0):
        st.debounce = cfg.occl_debounce          # blind corner: no time to confirm twice
    r.hold = False
    if st.level >= 2 and w_tr is not None and w_tr.speed > 0.5:
        st.intent = tuple(w_tr.vel)                # where the worker is heading while the alert is on
    # GO check: a worker who stopped for the alert no longer conflicts, but walking on would -
    # keep him waiting (and the forklift at passing speed) until the forklift is clear of his way
    go_blocked = (getattr(cfg, "go_check", False) and r.level < 2 and st.level >= 2 and st.intent is not None
                  and w_tr is not None and f_tr is not None and f_tr.speed > 0.2 and w_tr.speed < 0.5
                  and not go_safe(w_tr.pos, st.intent, f_tr, cfg))
    if go_blocked or r.level < 2 and st.level >= 2 and w_tr is not None and f_tr is not None \
            and f_tr.speed > 0.2 and waiting_at_lane(w_tr, f_tr, cfg):
        # keep the alert: pass the worker waiting at the lane edge at walking pace
        limit = round(min(cfg.pass_speed, f_tr.speed), 2)
        r.level, r.level_name = 2, LEVELS[2]
        r.reason = ("worker waiting: forklift still to pass his way" if go_blocked
                    else "worker waiting at the lane edge: pass at walking pace")
        r.speed_limit, r.speed_scale = limit, round(limit / max(f_tr.speed, 1e-6), 2)
        r.hold = True
    ev = st.step(r.level, now)
    if ev == "raise":
        st.released = False
    if ev:
        st.last_any = now
    # GO for the worker as soon as the forklift is past him (separating, nothing predicted):
    # the forklift keeps its limit for clear_hold, the waiting worker need not
    if ev is None and getattr(cfg, "release_worker", False) and st.level >= 2 and r.level < 2 \
            and not st.released and r.closing_speed < -0.3 and r.range > cfg.r_safe + 1.5:
        st.released = True
        st.last_any = now
        return "release", {r.worker: {"release": True}}
    # a tighter speed limit must reach the forklift now, not at the next periodic refresh
    if ev is None and r.level >= 2 and st.level >= 2 and r.speed_limit is not None \
            and st.sent_limit is not None and r.speed_limit < st.sent_limit - 0.3:
        ev = "refresh"
        st.last_sent = now
    if not ev:
        # WAIT keep-alive: the tag holds the worker while it hears the alert; between refreshes
        # (level flickering, clear-hold window) it would otherwise time out and show GO early
        if getattr(cfg, "wait_keepalive", False) and st.level >= 2 and now - st.last_any >= st.refresh_s:
            st.last_any = now
            return "wait", {r.worker: {"wait": True}}
        return None, None
    st.sent_limit = None if ev == "clear" else r.speed_limit
    untagged = r.worker.startswith("untagged_")
    # vibrate on a new alert, while DANGER, and while the worker still walks into the
    # conflict (the speed plan assumes a buzzed worker stops); not on holds, so a
    # worker who has already stopped is not buzzed every second
    walking_in = w_tr is not None and w_tr.speed > 0.3 and r.closing_speed > 0.2
    buzz = ev == "raise" or (ev == "refresh" and not r.hold and (r.level >= 3 or walking_in))
    actions = {r.worker: {"vibrate": buzz and not untagged},
               r.forklift: {"beacon": ev != "clear" and r.level >= 2,
                            "speed_scale": 1.0 if ev == "clear" else r.speed_scale,
                            # absolute limit: a ratio of an already reduced speed
                            # would let the truck speed up again
                            "speed_limit": None if ev == "clear" else r.speed_limit}}
    return ev, actions
