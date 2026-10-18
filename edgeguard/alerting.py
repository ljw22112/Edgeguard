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
        self.no_intent_until = 0.0        # after STEP ASIDE his motion is the sidestep, not his way
        self.raise_t = None               # when this encounter's alert was raised (truck priority)
        self.sent_stop = None             # stop point last sent to the truck
        self.slow_since = None            # worker slower than 0.5 m/s since (STEP ASIDE only for one standing)
        self.aside_t = None               # when STEP ASIDE was sent

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


def _aside_vector(wpos, f_tr, f_speed, cfg, horizon=5.0, others=()):
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
    if d >= cfg.r_safe + getattr(cfg, "aside_reach", 0.3):
        return None
    qx, qy = pts[min(best + 1, len(pts) - 1)] if best + 1 < len(pts) else pts[best - 1]
    tx, ty = qx - px, qy - py                                   # path direction there
    tn = math.hypot(tx, ty) or 1.0
    nx, ny = -ty / tn, tx / tn                                  # path normal
    lat = (wpos[0] - px) * nx + (wpos[1] - py) * ny
    side = 1.0 if lat >= 0 else -1.0
    gap = cfg.r_safe + getattr(cfg, "aside_margin", 0.8)
    if not others:
        move = side * gap - lat
        return [round(nx * move, 2), round(ny * move, 2)]
    # the step must not take him towards another truck or onto its path: nearer edge first, else the other one
    for sd in ((side, -side) if abs(lat) < 0.3 else (side,)):    # never across the truck's path
        move = sd * gap - lat
        tgt = (wpos[0] + nx * move, wpos[1] + ny * move)
        if all(_spot_clear(tgt, wpos, o, cfg) for o in others if o is not f_tr):
            return [round(nx * move, 2), round(ny * move, 2)]
    return None


def _spot_clear(tgt, wpos, o, cfg):
    """A sidestep from wpos to tgt keeps clear of forklift track o (where it is and where it goes)."""
    import math
    from .risk import forklift_predictor
    if o.x is None:
        return True
    for k in range(5):                                          # along the step
        q = (wpos[0] + (tgt[0] - wpos[0]) * k / 4, wpos[1] + (tgt[1] - wpos[1]) * k / 4)
        if math.hypot(q[0] - o.pos[0], q[1] - o.pos[1]) < cfg.r_safe + 0.5:
            return False
    v = o.speed if abs(o.speed) > 0.3 else 1.0                  # a standing truck may move off along its heading
    pts = forklift_predictor(o, v).positions([i * 0.25 for i in range(1, 21)])
    return all(math.hypot(tgt[0] - x, tgt[1] - y) >= cfg.r_safe + 0.3 for x, y in pts)


def _walking(intent, cfg):
    """The waiting worker's intended velocity at his walking pace (direction kept)."""
    if intent is None or not getattr(cfg, "intent_v2", False):
        return intent
    n = math.hypot(intent[0], intent[1])
    ws = getattr(cfg, "walk_speed", 1.3)
    return intent if n >= ws or n < 1e-6 else (intent[0] / n * ws, intent[1] / n * ws)


def envelope_limit(w_tr, f_tr, cfg, held=False, out_stop=None):
    """Speed at which the truck can still stop short of a person near its path ahead (reaction env_react, then
    brake_decel, stopping r_safe before him), or None when nobody is near its path."""
    if w_tr is None or f_tr is None or w_tr.x is None or f_tr.x is None:
        return None
    if getattr(cfg, "env_v2", False):
        return _envelope_v2(w_tr, f_tr, cfg, held, out_stop)
    if abs(f_tr.speed) < 0.5:
        return None
    look = getattr(cfg, "env_look", 0.0)
    if look > 0 and w_tr.speed > 0.3:
        # also where he will be by the time he has stopped (still walking: reaction + slow-down)
        wx, wy = w_tr.vel
        later = _Pt((w_tr.pos[0] + wx * look, w_tr.pos[1] + wy * look))
        a, b = _envelope_at(w_tr.pos, f_tr, cfg), _envelope_at(later.pos, f_tr, cfg)
        return a if b is None else b if a is None else min(a, b)
    return _envelope_at(w_tr.pos, f_tr, cfg)


class _Pt:
    def __init__(self, pos):
        self.pos = pos


def _envelope_at(wpos, f_tr, cfg):
    vx, vy = f_tr.vel
    sp = math.hypot(vx, vy)
    if sp < 0.3:
        return None
    ux, uy = vx / sp, vy / sp
    dx, dy = wpos[0] - f_tr.pos[0], wpos[1] - f_tr.pos[1]
    ahead, lat = dx * ux + dy * uy, abs(-dx * uy + dy * ux)
    if ahead <= 0 or ahead > 15.0 or lat > cfg.env_lateral:
        return None
    room = max(0.0, ahead - cfg.r_safe)
    a, tr = cfg.brake_decel, cfg.env_react
    return a * (-tr + math.sqrt(tr * tr + 2.0 * room / a))


def _lat_to_leave(w_tr, f_tr, cfg):
    """How far the worker still has to move sideways to be out of the truck's path (r_safe from its line)."""
    vx, vy = f_tr.vel
    vn = math.hypot(vx, vy)
    if vn > 0.3:
        ux, uy = vx / vn, vy / vn
    elif f_tr.heading is not None:
        ux, uy = math.cos(f_tr.heading), math.sin(f_tr.heading)
    else:
        return 0.0
    dx, dy = w_tr.pos[0] - f_tr.pos[0], w_tr.pos[1] - f_tr.pos[1]
    return max(0.0, cfg.r_safe + 0.2 - abs(-dx * uy + dy * ux))


def entry_gate_needed(w_tr, f_tr, cfg):
    """A walker heading into the truck's path whose stopping point after a late alert would be inside it, and
    the truck reaches his crossing within gate_t before he can be across."""
    sp = abs(f_tr.speed)
    vx, vy = f_tr.vel
    vn = math.hypot(vx, vy)
    if sp < 0.8 or vn < 0.3:
        return False
    ux, uy = vx / vn, vy / vn
    dx, dy = w_tr.pos[0] - f_tr.pos[0], w_tr.pos[1] - f_tr.pos[1]
    ahead, lat_s = dx * ux + dy * uy, -dx * uy + dy * ux
    wvx, wvy = w_tr.vel
    toward = -(wvx * -uy + wvy * ux) * (1.0 if lat_s > 0 else -1.0)
    rs, lat = cfg.r_safe, abs(lat_s)
    if toward < 0.5 or lat <= rs or ahead <= 0:
        return False
    # where he stops if the alert comes at the usual time: warning lead + reaction + slowing down
    t_late = 0.8 + 0.3
    stop_lat = lat - toward * (t_late + toward / 4.0)
    if stop_lat >= rs:
        return False                                          # a later alert still stops him outside
    if lat - toward * 0.8 - toward * toward / 4.0 < rs + 0.2:
        return False                                          # too late to stop him outside anyway
    t_out = (lat + rs) / toward
    t_f_in = (ahead - rs) / sp
    return t_f_in < min(t_out, getattr(cfg, "gate_t", 6.0))


def green_wave_speed(w_tr, f_tr, cfg):
    """Speed at which the truck reaches the crossing just after a walking worker has crossed its path, or None.

    Only when the worker walks across the path (towards its line faster than 0.5 m/s), the crossing is within
    gw_horizon, the truck would otherwise meet him there, and the slower speed is at least gw_min_frac of its
    speed (a gentle slow-down well before any braking would be needed)."""
    sp = abs(f_tr.speed)
    if sp < 0.8:
        return None
    vx, vy = f_tr.vel
    vn = math.hypot(vx, vy)
    if vn < 0.3:
        return None
    ux, uy = vx / vn, vy / vn
    dx, dy = w_tr.pos[0] - f_tr.pos[0], w_tr.pos[1] - f_tr.pos[1]
    ahead, lat_s = dx * ux + dy * uy, -dx * uy + dy * ux
    wvx, wvy = w_tr.vel
    toward = -(wvx * -uy + wvy * ux) * (1.0 if lat_s > 0 else -1.0)
    along = wvx * ux + wvy * uy
    rs, lat = cfg.r_safe, abs(lat_s)
    if toward < 0.5 or ahead <= rs:
        return None
    m = getattr(cfg, "gw_margin", 0.6)
    t_in, t_out = max(0.0, (lat - rs) / toward), (lat + rs) / toward
    if t_out > getattr(cfg, "gw_horizon", 8.0):
        return None
    a_cross = ahead + along * t_out                           # where he crosses, along the truck's path
    if a_cross - rs <= 0:
        return None
    t_f_in, t_f_out = (a_cross - rs) / sp, (a_cross + rs) / sp
    if t_f_out < t_in - m or t_f_in > t_out + m:
        return None                                          # they do not meet at this speed
    v = (a_cross - rs) / (t_out + m)
    if v < getattr(cfg, "gw_min_frac", 0.5) * sp or v >= sp - 0.1:
        return None
    if a_cross - rs < sp * cfg.env_react + sp * sp / (2 * cfg.brake_decel) + 1.0:
        return None                                          # too close for a gentle plan: the envelope decides
    return v


def _v_stop(room, cfg):
    a, tr = cfg.brake_decel, cfg.env_react
    return a * (-tr + math.sqrt(tr * tr + 2.0 * max(0.0, room) / a))


def _envelope_v2(w_tr, f_tr, cfg, held=False, out_stop=None):
    """Stopping envelope that also covers a person beside the path who walks (or starts to walk) into it.

    In the path (closer than r_safe to its line): the truck may only go as fast as it can still stop short of him.
    Beside it: he needs t_reach to get within r_safe of the line (walking towards it: at his speed; otherwise
    detection env_detect + the gap at walk_speed); the truck is safe if it can stop short of where he would step
    in, or if at its speed it is past him before he can get there.  Returns a speed cap or None."""
    sp = abs(f_tr.speed)
    vx, vy = f_tr.vel
    vn = math.hypot(vx, vy)
    if vn > 0.3:
        ux, uy = vx / vn, vy / vn
    elif f_tr.heading is not None:
        sgn = -1.0 if f_tr.speed < 0 else 1.0
        ux, uy = sgn * math.cos(f_tr.heading), sgn * math.sin(f_tr.heading)
    else:
        return None
    dx, dy = w_tr.pos[0] - f_tr.pos[0], w_tr.pos[1] - f_tr.pos[1]
    ahead, lat_s = dx * ux + dy * uy, -dx * uy + dy * ux
    lat = abs(lat_s)
    rs = cfg.r_safe
    if ahead <= -rs or ahead > 20.0 or lat > cfg.env_lateral:
        return None
    wvx, wvy = w_tr.vel
    toward = -(wvx * -uy + wvy * ux) * (1.0 if lat_s > 0 else -1.0)      # his speed towards the path line
    if getattr(cfg, "env_walk_in", False) and toward > 0.3 and lat < rs + 1.0:
        lat = 0.0                                            # walking into the path: stop short of its middle
    if lat < rs:                                             # in the path
        if ahead <= 0:
            return 0.0                                       # beside the front of the truck: do not move
        d = ahead - math.sqrt(rs * rs - lat * lat) - getattr(cfg, "env_margin", 0.3)
        if out_stop is not None:                             # movement authority: stop short of this point
            out_stop.append([round(f_tr.pos[0] + ux * max(d, 0.0), 2), round(f_tr.pos[1] + uy * max(d, 0.0), 2)])
        return _v_stop(d, cfg)
    if held and w_tr.speed < 0.3:
        # told to WAIT and standing: he stays put - only right at the path is he passed no faster than
        # env_held_floor (in case he walks on anyway)
        hf = getattr(cfg, "env_held_floor", 0.0)
        if hf > 0 and lat - rs < getattr(cfg, "env_held_gap", 1.0) and 0 < ahead and hf < sp:
            return hf
        return None
    if toward > 0.3:
        t_reach = (lat - rs) / toward
    else:
        t_reach = getattr(cfg, "env_detect", 0.7) + (lat - rs) / getattr(cfg, "walk_speed", 1.3)
    if ahead + rs <= max(sp, 0.0) * t_reach:
        return None                                          # past him before he can get there
    lim = _v_stop(ahead - rs, cfg)
    if toward <= 0.3:                                        # standing / walking along: may be passed at the floor
        lim = max(lim, getattr(cfg, "env_pass_floor", 1.0))
    return lim if lim < sp else None


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
        vmin = getattr(cfg, "intent_min_speed", 0.5)
        if w_tr is not None and w_tr.speed > vmin and not st.aside_sent and now >= st.no_intent_until \
                and now >= getattr(w_tr, "no_intent_until", 0.0) and (st.level < 2 or st.intent is None):
            vx, vy = w_tr.vel
            if st.intent is None or st.level >= 2:
                st.intent = (vx, vy)
            else:                                  # smoothed: one noisy fix does not turn his way
                st.intent = (0.7 * st.intent[0] + 0.3 * vx, 0.7 * st.intent[1] + 0.3 * vy)
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
    # a worker counts as standing for STEP ASIDE only once he has been slow for aside_still_s (with noisy fixes a
    # walking worker's speed dips below 0.5 m/s now and then; a sidestep planned from where he was is then wrong)
    if w_tr is not None and w_tr.speed < 0.5:
        st.slow_since = st.slow_since if st.slow_since is not None else now
    else:
        st.slow_since = None
    still = st.slow_since is not None and now - st.slow_since >= getattr(cfg, "aside_still_s", 0.0)
    early = getattr(cfg, "truck_priority", False) and getattr(cfg, "early_aside", False)
    ahead_m = getattr(cfg, "aside_ahead_m", 0.0) if getattr(cfg, "truck_priority", False) else 0.0
    if getattr(cfg, "aside_cue", False) and (st.level >= 2 or early and r.level >= 2 or ahead_m > 0) and not st.aside_sent \
            and w_tr is not None and f_tr is not None and (w_tr.speed < 0.5 and still or early or ahead_m > 0) \
            and not r.worker.startswith("untagged_"):
        side = _aside_vector(w_tr.pos, f_tr, st.f_speed, cfg,
                             others=others if getattr(cfg, "aside_check_others", False) else ())
        if side is not None and st.level < 2 and r.level < 2 and ahead_m > 0 \
                and math.hypot(w_tr.pos[0] - f_tr.pos[0], w_tr.pos[1] - f_tr.pos[1]) > ahead_m:
            side = None                            # on its path, but still far: not yet
        if side is not None and (st.level >= 2 or r.level >= 2 or abs(f_tr.speed) > 0.5):
            new = st.level < 2                     # the first cue of this encounter (counts as an alarm)
            st.aside_sent = True
            st.aside_t = now
            st.no_intent_until = now + 5.0
            w_tr.no_intent_until = now + 5.0       # the sidestep is not his way for any other truck either
            st.last_any = now
            if new:
                st.level, st.last_sent, st.below_since = 2, now, None   # the encounter is on: WAIT after the step
            return "aside", {r.worker: {"aside": side, "vibrate": True, "new": new}}
    go_blocked = worker_first = stepping = by_other = False
    walk = _walking(st.intent, cfg)
    if walk is None and getattr(cfg, "go_unknown_worst", False) and st.level >= 2 and w_tr is not None \
            and f_tr is not None and abs(f_tr.speed) > 0.2:
        # where he wants to go is not known (he stood, or stepped aside): GO only if walking straight at the
        # truck's path would be safe too
        vx, vy = f_tr.vel
        vn = math.hypot(vx, vy) or 1.0
        ux, uy = vx / vn, vy / vn
        dx, dy = w_tr.pos[0] - f_tr.pos[0], w_tr.pos[1] - f_tr.pos[1]
        side = 1.0 if (-dx * uy + dy * ux) > 0 else -1.0
        ws = getattr(cfg, "walk_speed", 1.3)
        walk = (side * uy * ws, -side * ux * ws)               # towards the path line
        if st.intent is None:
            st.intent_guess = True
    # both stopped close together and we do not know where he wants to go: releasing both at once is
    # how a standoff turns into a collision, so treat it as unsafe and let one go first
    standoff = (getattr(cfg, "standoff_unknown", False) and st.intent is None and w_tr is not None and f_tr is not None
                and abs(f_tr.speed) <= 0.2 and st.f_speed is not None
                and math.hypot(w_tr.pos[0] - f_tr.pos[0], w_tr.pos[1] - f_tr.pos[1]) < cfg.r_safe + 3.0)
    guess = walk is not None and st.intent is None
    if (getattr(cfg, "go_check", False) and r.level < 2 and st.level >= 2 and (st.intent is not None or standoff or guess)
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
        creep = getattr(cfg, "aside_hold_speed", 0.0)
        if stepping and creep > 0 and r.range > 5.0:
            r.speed_limit = creep                  # far enough: roll on slowly while he steps aside
            r.speed_scale = round(creep / max(abs(f_tr.speed), 1e-6), 2)
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
    r.quiet = False
    r.stop_at = None
    r.glide = False
    if getattr(cfg, "entry_gate", False) and r.level < 2 and w_tr is not None and f_tr is not None \
            and entry_gate_needed(w_tr, f_tr, cfg):
        # he walks towards the truck's path and would stop inside it if told later: tell him now, while he can
        # still stop outside (the truck then passes instead of braking for a person standing in its lane)
        r.level, r.level_name = 2, LEVELS[2]
        r.reason = "stop before the forklift's path"
    if getattr(cfg, "green_wave", False) and r.level < 2 and w_tr is not None and f_tr is not None:
        v_gw = green_wave_speed(w_tr, f_tr, cfg)
        if v_gw is not None:
            # a walker will cross the truck's path ahead: slow the truck a little now so it arrives just after he
            # has crossed - nobody stops (the worker is not buzzed, he walks on)
            r.level, r.level_name = 2, LEVELS[2]
            r.reason = "green wave: arrive after the worker has crossed"
            r.speed_limit = round(v_gw, 2)
            r.speed_scale = round(v_gw / max(abs(f_tr.speed), 1e-6), 2)
            r.hold = r.quiet = True
    if getattr(cfg, "env_cap", False) and r.level < 2:
        stop = [] if getattr(cfg, "stop_point", False) else None
        lim = envelope_limit(w_tr, f_tr, cfg, held=st.level >= 2, out_stop=stop)
        ref = max(abs(f_tr.speed), abs(st.f_speed or 0.0)) if getattr(cfg, "env_v2", False) else abs(f_tr.speed)
        if lim is not None and lim < ref - 0.2:
            # someone close to the truck's path: it may only go as fast as it can still stop if he steps in;
            # the worker is not buzzed (nothing is predicted), only the truck is limited
            r.level, r.level_name = 2, LEVELS[2]
            r.reason = "person near the path: speed for the stopping distance"
            r.speed_limit = round(max(lim, 0.0), 2)
            r.speed_scale = round(r.speed_limit / max(abs(f_tr.speed), 1e-6), 2)
            r.hold = r.quiet = True
            if getattr(cfg, "env_buzz_walker", False) and w_tr is not None and w_tr.speed > 0.5 \
                    and r.closing_speed > 0.3:
                r.quiet = False                    # he walks towards the truck: tell him to WAIT (he yields)
            if stop:
                r.stop_at = stop[0]
    if getattr(cfg, "truck_priority", False) and r.level >= 2 and r.level < 3 and f_tr is not None and w_tr is not None \
            and not worker_first:
        # the worker yields (WAIT, or STEP ASIDE when he is on the truck's path), the truck keeps its speed as
        # long as it can still stop short of where he is - or of where he will have stopped if he still walks
        plan = r.speed_limit
        stop = [] if getattr(cfg, "stop_point", False) else None
        lim = envelope_limit(w_tr, f_tr, cfg, held=st.level >= 2 or r.level >= 2, out_stop=stop)
        # still walking into the conflict well after the alert: he did not stop, plan for him as he walks
        grace = getattr(cfg, "comply_grace", 0.0)
        if grace > 0 and plan is not None and w_tr.speed > 0.5 and r.closing_speed > 0.2 \
                and st.raise_t is not None and now - st.raise_t > grace:
            lim = plan if lim is None else min(lim, plan)
        if getattr(cfg, "env_v2", False):
            r.speed_limit = None if lim is None else round(max(lim, 0.0), 2)
            if stop:
                r.stop_at = stop[0]                    # the module brakes for the point itself; the limit is
                                                       # for modules without stop points
                # glide: he is stepping out of the path - roll slowly so the truck reaches the stop point when
                # he is out, instead of braking into it, standing and speeding up again (1 m/s^2)
                if getattr(cfg, "glide", False) and st.aside_sent and getattr(st, "aside_t", None) is not None:
                    t_out = max(0.0, st.aside_t + 0.8 - now) + _lat_to_leave(w_tr, f_tr, cfg) / 1.0 + 0.3
                    d = math.hypot(stop[0][0] - f_tr.pos[0], stop[0][1] - f_tr.pos[1])
                    if t_out > 0.2:
                        v = max(getattr(cfg, "glide_min", 0.5), d / t_out)
                        if r.speed_limit is None or v < r.speed_limit:
                            r.speed_limit = round(v, 2)
                            r.glide = True
        else:
            r.speed_limit = round(max(lim, 0.0), 2) if lim is not None and lim < abs(f_tr.speed) - 0.1 else None
        r.speed_scale = 1.0 if r.speed_limit is None else round(r.speed_limit / max(abs(f_tr.speed), 1e-6), 2)
    elif getattr(cfg, "truck_priority", False) and getattr(cfg, "stop_point", False) and r.level >= 2 \
            and f_tr is not None and w_tr is not None:
        # DANGER or "worker first": the plan's own limit stands, and a person in the path is also a stop point
        stop = []
        envelope_limit(w_tr, f_tr, cfg, held=True, out_stop=stop)
        if stop:
            r.stop_at = stop[0]
    if st.aside_sent:
        st.hold_s = min(st.hold_s, 1.0)           # worker parked at the lane edge: no flicker to ride out
    ev = st.step(r.level, now)
    if ev == "raise":
        st.raise_t = now
    elif ev == "clear":
        st.raise_t = None
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
    sent = st.sent_limit if st.sent_limit is not None or not getattr(cfg, "prompt_ease", False) else math.inf
    if ev is None and r.level >= 2 and st.level >= 2 and r.speed_limit is not None \
            and sent is not None and r.speed_limit < sent - 0.3 \
            and (getattr(r, "stop_at", None) is None or getattr(st, "sent_stop", None) is None
                 or getattr(r, "glide", False)):
        ev = "refresh"
        st.last_sent = now
    # a stop point does not creep away with position noise: within the encounter it only moves closer, or
    # farther once he has really moved (by more than stop_hold_m)
    ss = getattr(st, "sent_stop", None)
    if getattr(r, "stop_at", None) is not None and ss is not None and f_tr is not None:
        dn = math.hypot(r.stop_at[0] - f_tr.pos[0], r.stop_at[1] - f_tr.pos[1])
        do = math.hypot(ss[0] - f_tr.pos[0], ss[1] - f_tr.pos[1])
        if do < dn < do + getattr(cfg, "stop_hold_m", 1.0):
            r.stop_at = list(ss)
    # a new stop point, or one that moved closer, must reach the module now
    if ev is None and getattr(r, "stop_at", None) is not None and st.level >= 2 and f_tr is not None:
        ss = getattr(st, "sent_stop", None)
        closer = ss is None or (math.hypot(r.stop_at[0] - f_tr.pos[0], r.stop_at[1] - f_tr.pos[1])
                                < math.hypot(ss[0] - f_tr.pos[0], ss[1] - f_tr.pos[1]) - 0.3)
        if closer:
            ev = "refresh"
            st.last_sent = now
    # prompt ease: the truck's limit follows the current plan when it gets looser too, instead of waiting
    # for the periodic refresh or the end of the clear hold (the worker's WAIT is unaffected)
    if ev is None and getattr(cfg, "prompt_ease", False) and st.level >= 2 and st.sent_limit is not None \
            and now - st.last_sent >= getattr(cfg, "ease_min_s", 0.3) and w_tr is not None and f_tr is not None:
        new = r.speed_limit if r.level >= 2 else None
        settled = w_tr.speed < 0.3 or r.closing_speed < -0.3      # he stopped for the alert, or they separate
        if getattr(cfg, "ease_on_leave", False) and getattr(st, "sent_stop", None) is not None \
                and getattr(r, "stop_at", None) is None:
            settled = True                         # he has left the truck's path: its stop point can go
        if settled and getattr(r, "stop_at", None) is None and (new is None or new > st.sent_limit + 0.3):
            ev = "refresh"
            st.last_sent = now
            if new is None:
                r.speed_limit, r.speed_scale = None, 1.0
    if not ev:
        # WAIT keep-alive: the tag holds the worker while it hears the alert; between refreshes
        # (level flickering, clear-hold window) it would otherwise time out and show GO early
        if getattr(cfg, "wait_keepalive", False) and st.level >= 2 and not st.released \
                and now - st.last_any >= st.refresh_s:
            st.last_any = now
            return "wait", {r.worker: {"wait": True}}
        return None, None
    st.sent_limit = None if ev == "clear" else r.speed_limit
    st.sent_stop = None if ev == "clear" else getattr(r, "stop_at", None)
    untagged = r.worker.startswith("untagged_")
    # vibrate on a new alert, while DANGER, and while the worker still walks into the
    # conflict (the speed plan assumes a buzzed worker stops); not on holds, so a
    # worker who has already stopped is not buzzed every second
    walking_in = w_tr is not None and w_tr.speed > 0.3 and r.closing_speed > 0.2
    buzz = ev == "raise" or (ev == "refresh" and not r.hold and (r.level >= 3 or walking_in))
    actions = {r.worker: {"vibrate": buzz and not untagged and not getattr(r, "quiet", False)},
               r.forklift: {"beacon": ev != "clear" and r.level >= 2,
                            "speed_scale": 1.0 if ev == "clear" else r.speed_scale,
                            # absolute limit: a ratio of an already reduced speed
                            # would let the truck speed up again
                            "speed_limit": None if ev == "clear" else r.speed_limit,
                            "stop_at": None if ev == "clear" else getattr(r, "stop_at", None)}}
    return ev, actions
