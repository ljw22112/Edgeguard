"""Alert policy: turns per-pair risk assessments into alert events and device actions.

Shared by the MEC app and the simulators, so what is trained and evaluated in
simulation is exactly what runs on the MEC host.
"""
from __future__ import annotations

import math

from .risk import LEVELS, go_safe, path_clearance, truck_path_clear, waiting_at_lane


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
        self.f_speed = None               # forklift speed before the alert slowed it (it resumes on clear)
        self.aside_sent = False           # STEP ASIDE already sent in this encounter
        self.last_any = 0.0               # last message of any kind for this pair (WAIT keep-alive)

    def reset(self):
        self.level, self.streak, self.below_since, self.sent_limit, self.last_eval = 0, 0, None, None, None
        self.released, self.intent, self.f_speed, self.aside_sent = False, None, None, False

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


def _aside_vector(wpos, f_tr, f_speed, cfg, horizon=5.0):
    """Sideways displacement (site frame) that takes a worker standing on the truck's predicted
    path (CTRV at its cruising speed, so a turn counts) to r_safe + 0.8 m from it, or None if
    he is not on it."""
    import math
    from .risk import forklift_predictor
    v = f_speed if f_speed and abs(f_speed) > abs(f_tr.speed) else f_tr.speed
    if abs(v) < 0.3:
        return None
    pts = forklift_predictor(f_tr, v).positions([i * 0.2 for i in range(1, int(horizon / 0.2) + 1)])
    best = min(range(len(pts)), key=lambda i: math.hypot(wpos[0] - pts[i][0], wpos[1] - pts[i][1]))
    px, py = pts[best]
    d = math.hypot(wpos[0] - px, wpos[1] - py)
    if d >= cfg.r_safe + 0.3:
        return None
    qx, qy = pts[min(best + 1, len(pts) - 1)] if best + 1 < len(pts) else pts[best - 1]
    tx, ty = qx - px, qy - py                                   # path direction there
    tn = math.hypot(tx, ty) or 1.0
    nx, ny = -ty / tn, tx / tn                                  # path normal
    lat = (wpos[0] - px) * nx + (wpos[1] - py) * ny
    side = 1.0 if lat >= 0 else -1.0
    move = side * (cfg.r_safe + 0.8) - lat
    return [round(nx * move, 2), round(ny * move, 2)]


def _walking(intent, cfg):
    """The waiting worker's intended velocity at his walking pace (direction kept)."""
    if intent is None or not getattr(cfg, "intent_v2", False):
        return intent
    n = math.hypot(intent[0], intent[1])
    ws = getattr(cfg, "walk_speed", 1.3)
    return intent if n >= ws or n < 1e-6 else (intent[0] / n * ws, intent[1] / n * ws)


def decide(st: AlertState, r, w_tr, f_tr, cfg, now, congested=False, others=()):
    """Update the pair's alert state with assessment `r`.

    Returns (event or None, actions dict).  May modify `r` (hold logic)."""
    st.refresh_s = 0.5 if congested else 1.0
    st.debounce, st.hold_s = cfg.debounce, cfg.clear_hold
    if getattr(r, "occluded", False) and getattr(cfg, "occl_debounce", 0):
        st.debounce = cfg.occl_debounce          # blind corner: no time to confirm twice
    r.hold = False
    if getattr(cfg, "intent_v2", False):
        # walking before the alert: that is where he wants to go; during the alert only if still unknown
        # (later motion is the slow-down into the stop or a sidestep, not his way)
        if w_tr is not None and w_tr.speed > 0.5 and not st.aside_sent and (st.level < 2 or st.intent is None):
            st.intent = tuple(w_tr.vel)
    elif st.level >= 2 and w_tr is not None and w_tr.speed > 0.5 and not st.aside_sent:
        st.intent = tuple(w_tr.vel)                # where the worker is heading (not his sidestep)
    if f_tr is not None and abs(f_tr.speed) > 0.5 and (st.f_speed is None or abs(f_tr.speed) > abs(st.f_speed)):
        st.f_speed = f_tr.speed                    # fastest seen (signed): what the truck returns to when let go
    # GO check: a worker who stopped for the alert no longer conflicts, but walking on would -
    # keep him waiting (and the forklift at passing speed) until the forklift is clear of his way
    # (a truck that stopped for him counts at its cruising speed: clearing the pair releases both,
    # and two parties starting at the same moment is how a standoff turns into a collision)
    # STEP ASIDE: the worker stands in the lane of a truck that stopped for him - nobody can pass,
    # so he is told to step to the nearer lane edge (and WAIT there) instead of holding both
    if getattr(cfg, "aside_cue", False) and st.level >= 2 and not st.aside_sent and w_tr is not None \
            and f_tr is not None and w_tr.speed < 0.5:
        side = _aside_vector(w_tr.pos, f_tr, st.f_speed, cfg)
        if side is not None:
            st.aside_sent = True
            st.last_any = now
            return "aside", {r.worker: {"aside": side, "vibrate": True}}
    go_blocked = worker_first = stepping = by_other = False
    walk = _walking(st.intent, cfg)
    # both stopped close together and we do not know where he wants to go: releasing both at once is
    # how a standoff turns into a collision, so treat it as unsafe and let one go first
    standoff = (getattr(cfg, "standoff_unknown", False) and st.intent is None and w_tr is not None and f_tr is not None
                and abs(f_tr.speed) <= 0.2 and st.f_speed is not None
                and math.hypot(w_tr.pos[0] - f_tr.pos[0], w_tr.pos[1] - f_tr.pos[1]) < cfg.r_safe + 3.0)
    if (getattr(cfg, "go_check", False) and r.level < 2 and st.level >= 2 and (st.intent is not None or standoff)
            and w_tr is not None and f_tr is not None and (f_tr.speed > 0.2 or st.f_speed)
            and (w_tr.speed < 0.5 or st.aside_sent)          # waiting, or still stepping aside
            and (standoff or not go_safe(w_tr.pos, walk, f_tr, cfg, st.f_speed))):
        # one of them must go first: the truck if its way past the waiting worker is clear,
        # otherwise the worker (he stands in the truck's way) while the truck stays stopped
        sign = -1.0 if (st.f_speed or f_tr.speed) < 0 else 1.0
        if truck_path_clear(w_tr.pos, f_tr, cfg, sign * cfg.pass_speed):
            go_blocked = True
        elif st.aside_sent:                        # told to step aside: the truck waits until he is out of its way
            stepping = True
        else:
            worker_first = True
    # ... and no other truck may be on his way either: GO is for the worker, not for one pair
    # (others = the other forklift tracks; a truck he waits for here passes at passing speed)
    if (not (go_blocked or worker_first or stepping) and others and getattr(cfg, "go_check", False)
            and getattr(cfg, "go_check_all", True)
            and r.level < 2 and st.level >= 2 and st.intent is not None and w_tr is not None and f_tr is not None
            and (w_tr.speed < 0.5 or st.aside_sent)
            and any(o is not f_tr and abs(o.speed) > 0.2 and math.hypot(o.pos[0] - w_tr.pos[0], o.pos[1] - w_tr.pos[1]) < 25.0
                    and not go_safe(w_tr.pos, walk, o, cfg) for o in others)):
        go_blocked = by_other = True
    if worker_first or stepping:
        r.level, r.level_name = 2, LEVELS[2]
        r.reason = ("worker stepping aside: forklift holds" if stepping
                    else "worker first: forklift holds until he has crossed")
        r.speed_limit, r.speed_scale = 0.0, 0.0
        r.hold = True
    elif go_blocked or r.level < 2 and st.level >= 2 and w_tr is not None and f_tr is not None \
            and f_tr.speed > 0.2 and waiting_at_lane(w_tr, f_tr, cfg):
        # keep the alert: pass the worker waiting at the lane edge at walking pace
        # the waiting worker stays put: a truck that stopped for him moves off at passing speed first
        sign = -1.0 if (st.f_speed or f_tr.speed) < 0 else 1.0
        cruise = st.f_speed if st.f_speed is not None else f_tr.speed
        if by_other and getattr(cfg, "free_other_hold", False) and w_tr.speed < 0.3 \
                and truck_path_clear(w_tr.pos, f_tr, cfg, cruise):
            limit = None                           # he waits for another truck; this one's way is clear
        else:
            limit = cfg.pass_speed if go_blocked else min(cfg.pass_speed, f_tr.speed)
            far = getattr(cfg, "pass_speed_far", 0.0)
            if far > limit and w_tr.speed < 0.3 \
                    and path_clearance(w_tr.pos, f_tr, cfg, sign * far) >= cfg.r_safe + getattr(cfg, "pass_margin", 1.0):
                limit = far                        # standing well clear of the truck's path
            limit = round(limit, 2)
        r.level, r.level_name = 2, LEVELS[2]
        r.reason = ("worker waiting: a forklift still to pass his way" if go_blocked
                    else "worker waiting at the lane edge: pass at walking pace")
        if limit is None:
            r.reason = "worker waiting for another forklift: this one passes"
        r.speed_limit = limit
        r.speed_scale = 1.0 if limit is None else round(limit / max(f_tr.speed, 1e-6), 2)
        r.hold = True
    if st.aside_sent:
        st.hold_s = min(st.hold_s, 1.0)           # worker parked at the lane edge: no flicker to ride out
    ev = st.step(r.level, now)
    if ev in ("raise", "clear"):
        st.released = st.aside_sent = False        # a new encounter may need a new GO / STEP ASIDE
    if ev:
        st.last_any = now
    # GO for the worker as soon as the forklift is past him (separating, nothing predicted):
    # the forklift keeps its limit for clear_hold, the waiting worker need not
    if ev is None and getattr(cfg, "release_worker", False) and st.level >= 2 and r.level < 2 \
            and not st.released and r.closing_speed < -0.3 and r.range > cfg.r_safe + 1.5:
        st.released = True
        st.last_any = now
        return "release", {r.worker: {"release": True}}
    # worker first: once the truck has been told to stay stopped, tell the worker GO
    if worker_first and ev is None and not st.released and st.sent_limit is not None and st.sent_limit <= 0.3:
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
        if getattr(cfg, "wait_keepalive", False) and st.level >= 2 and not st.released \
                and now - st.last_any >= st.refresh_s:
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
