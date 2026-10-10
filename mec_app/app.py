"""EdgeGuard MEC application.

Runs on the MEC host next to the site.  The CSE notifies it of every new
location / motion contentInstance; it updates the tracks, runs the guidance
risk engine and writes `risk` (summary) and `alert` (actions) back to the CSE,
where the worker tag and forklift module are subscribed.

    uvicorn mec_app.app:app --host 0.0.0.0 --port 9090
"""
from __future__ import annotations

import logging
import math
import os
import itertools
import json
import queue
import sys
import threading
import time
from collections import deque

from fastapi import FastAPI, Request, Response
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard import config                          # noqa: E402
from edgeguard.onem2m import parse_notification, now_ms  # noqa: E402
from edgeguard.risk import RiskEngine, LEVELS               # noqa: E402
from edgeguard.alerting import AlertState, decide            # noqa: E402
from edgeguard.tracking import Track                  # noqa: E402

log = logging.getLogger("edgeguard.mec")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CFG = config.load()
PATHS = config.paths(CFG)
MEC = CFG["mec"]
from edgeguard.sitemap import from_config as sitemap_from_config   # noqa: E402
SITEMAP = sitemap_from_config(CFG)
engine = RiskEngine(config.risk_config(CFG), method=MEC.get("method", "guidance_ctrv"), sitemap=SITEMAP or None)
cse = config.client(CFG)
# priority outbox: alerts (0) are written before control (1) and risk summaries (2)
outbox: "queue.PriorityQueue[tuple[int, int, float, str, str, dict]]" = queue.PriorityQueue(maxsize=1000)
_seq = itertools.count()
PRIO = {"alert": 0, "control": 1, "risk": 2, "nearmiss": 3}
# Stale messages are worse than none while the CSE is slow or recovering: a heartbeat delivered
# late tells a forklift "MEC alive" when it is not, and an old alert is superseded by the 1 s
# refresh anyway.  Messages older than this when their turn comes are dropped.
TTL_S = {"alert": MEC.get("alert_ttl_s", 1.5), "control": MEC.get("control_ttl_s", 1.0),
         "risk": MEC.get("risk_ttl_s", 1.0), "nearmiss": 300.0}


HA = dict(MEC.get("ha") or {})
if os.environ.get("MEC_HA", "").lower() in ("1", "true", "yes"):   # compose `ha` profile
    HA["enabled"] = True
INSTANCE = os.environ.get("MEC_INSTANCE_ID") or HA.get("instance_id") or "mec"
# a second instance needs its own notification URL and subscription name
for _env, _key in (("MEC_NOTIFY_URL", "notify_url"), ("MEC_SUBSCRIPTION_RN", "subscription_rn")):
    if os.environ.get(_env):
        MEC[_key] = os.environ[_env]
lease = None                                   # edgeguard.ha.Lease when HA is enabled


def is_leader():
    return lease is None or lease.leader


def post(kind, con):
    if not is_leader():                        # standby: keep state warm, write nothing
        state["publisher"]["standby_skipped"] = state["publisher"].get("standby_skipped", 0) + 1
        return
    try:
        outbox.put_nowait((PRIO[kind], next(_seq), time.monotonic(), kind, PATHS[kind], con))
    except queue.Full:
        state["publisher"]["dropped_full"] += 1
        log.warning("outbox full, dropping %s", kind)
state = {"pairs": {}, "last_risk_pub": 0.0, "alerts_sent": 0, "rx": 0, "worker_cues": {"wait": 0, "release": 0, "aside": 0},
         "worker_cue": {}, "worker_aside": {},
         "m2m": {"in": {}, "out": {}}, "acks": {},
         "publisher": {"ok": 0, "failed": 0, "dropped_stale": 0, "dropped_full": 0, "last_ok": None,
                       "last_error": None},
         "input": {"bad": 0, "clock_skew": 0, "late": 0}, "gc": {"tracks_removed": 0},
         "network": {"cell_load": None, "congested": False}, "location_fixes": 0,
         "alert_log": deque(maxlen=60), "ingest_ms": deque(maxlen=200)}
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
lock = threading.Lock()


def publisher():
    """Write contentInstances to the CSE off the request path (stale entries dropped)."""
    pub = state["publisher"]
    while True:
        _, _, t_enq, kind, path, con = outbox.get()
        if time.monotonic() - t_enq > TTL_S[kind]:
            pub["dropped_stale"] += 1
            continue
        delay = MEC.get("emulated_extra_delay_ms", 0)
        if delay:
            time.sleep(delay / 1000)
        try:
            cse.create_cin(path, con)
            m2m_out = state["m2m"]["out"]
            m2m_out[path] = m2m_out.get(path, 0) + 1
            pub["ok"] += 1
            pub["last_ok"] = time.monotonic()
        except Exception as e:                       # keep the loop alive
            pub["failed"] += 1
            pub["last_error"] = f"{type(e).__name__}: {str(e)[:120]}"
            log.warning("publish to %s failed: %s", path, e)


threading.Thread(target=publisher, daemon=True).start()

# Optional cloud sync: risk summaries and alerts copied to the cloud IN-CSE
# (store-and-forward, see edgeguard/cloud_sync.py).
CLOUD = CFG.get("cloud_sync") or {}
cloud_sync = None
state["cloud"] = {"sent": 0, "failed_attempts": 0, "dropped": 0, "backlog": 0}
if CLOUD.get("enabled"):
    from edgeguard.cloud_sync import CloudSync
    from edgeguard.onem2m import OneM2MClient
    cloud_sync = CloudSync(OneM2MClient(CLOUD["base_url"], CLOUD["cse_rn"],
                                        CLOUD.get("origin", CFG["cse"]["origin"]),
                                        str(CLOUD.get("rvi", "2a")), timeout=2.0),
                           CLOUD.get("ae", "EdgeGuard"), capacity=CLOUD.get("backlog", 5000))
    state["cloud"] = cloud_sync.stats


def to_cloud(kind, con):
    if cloud_sync is not None:
        cloud_sync.put(kind, con)


# --- ETSI MEC services: network location + RNIS-aware alert margin -----------------------
# Two ways to get MEC data (mec_services.location_source):
#   cse    (default) MEC-IPE writes Location API (MEC 013) and RNIS (MEC 012) data into the CSE;
#          the MEC app discovers those containers, subscribes, and reads them as oneM2M
#          notifications - the path the Hackathon's MEC Sandbox provides (tools/mec_ipe.py is
#          our stand-in until the Sandbox's IPE is available).
#   direct the MEC app calls the MEC APIs itself.
# UWB tags stay the primary position source (sub-metre, 10 Hz); a network fix is used for a
# device whose UWB is silent, or for UEs that have no tag at all.
MS = CFG.get("mec_services") or {}
BASE_T = (engine.cfg.t_danger, engine.cfg.t_warn)
state["mec"] = {"location_fixes": 0, "skipped_uwb_fresh": 0, "unknown_ue": 0, "ipe_subscriptions": 0,
                "cell_loads": {}}
_FRAME = None


def _frame():
    global _FRAME
    if _FRAME is None:
        from edgeguard.mec_services import SiteFrame
        _FRAME = SiteFrame(MS["origin"]["lat"], MS["origin"]["lon"])
    return _FRAME


def ue_map():
    """Location API address -> {"id", "kind"}; `users` (worker id -> address) still works."""
    m = {a: dict(v) for a, v in (MS.get("ue_map") or {}).items()}
    for wid, addr in (MS.get("users") or {}).items():
        m.setdefault(addr, {"id": wid, "kind": "worker"})
    return m


UE_MAP = ue_map() if MS.get("enabled") else {}


def handle_mec_location(u: dict):
    """One MEC 013 UserInfo (from the CSE via MEC-IPE, or from a direct API call)."""
    from edgeguard.mec_services import parse_user_info
    info = parse_user_info(u, _frame())
    if info is None:
        return
    dev = UE_MAP.get(info["address"]) or UE_MAP.get(str(info["address"]).split(":")[-1])
    if dev is None:
        state["mec"]["unknown_ue"] += 1
        return
    tr = engine.tracks.get(dev["id"])
    seen = getattr(tr, "uwb_seen", None) if tr else None
    if seen is not None and time.monotonic() - seen < MS.get("uwb_stale_s", 0.5):
        state["mec"]["skipped_uwb_fresh"] += 1          # the tag is better: ignore the coarse fix
        return
    state["mec"]["location_fixes"] += 1
    state["location_fixes"] += 1
    handle_sample({"id": dev["id"], "kind": dev.get("kind", "worker"),
                   "ts": int(info["ts"] * 1000) if info["ts"] else now_ms(),
                   "x": info["x"], "y": info["y"], "pos_sigma": max(0.3, info["accuracy"]),
                   "source": "mec-location"})


def apply_cell_load(load):
    congested = load is not None and load >= MS.get("congestion_prb_pct", 80)
    if congested != state["network"]["congested"]:
        log.info("RNIS: cell load %s%% -> %s", load, "congested" if congested else "normal")
    state["network"] = {"cell_load": load, "congested": congested}
    margin = MS.get("congested_margin_s", 0.5) if congested else 0.0
    engine.cfg.t_danger, engine.cfg.t_warn = BASE_T[0] + margin, BASE_T[1] + margin


def handle_mec_cell(c: dict):
    from edgeguard.mec_services import cell_load_of
    cell = ((c.get("ecgi") or {}).get("cellId")) or c.get("cellId")
    load = cell_load_of(c)
    if cell is None or load is None:
        return
    loads = state["mec"]["cell_loads"]
    loads[cell] = load
    want = MS.get("cell_id")
    apply_cell_load(loads.get(want) if want else max(loads.values()))


def is_mec_location(p):
    return isinstance(p, dict) and ("locationInfo" in p or ("address" in p and "latitude" in p))


def is_mec_cell(p):
    return isinstance(p, dict) and ("ecgi" in p or "dl_gbr_prb_usage_cell" in p)


def ipe_watch():
    """Find MEC-IPE containers in the CSE and subscribe the MEC app to each (new UEs and cells
    appear over time, so discovery repeats)."""
    root = (MS.get("ipe") or {}).get("root", "MEC-IPE")
    cl = config.client(CFG)
    done = set()
    while True:
        for group in ("location", "rnis"):
            try:
                paths = cl.discover(f"{root}/{group}")
            except Exception as e:
                log.debug("IPE discovery %s failed: %s", group, e)
                continue
            for pth in paths:
                if pth in done or pth.rstrip("/").endswith(f"{root}/{group}"):
                    continue
                try:
                    cl.create_subscription(pth, "sub_edgeguard", [MEC["notify_url"]])
                    done.add(pth)
                except Exception as e:
                    log.warning("subscribe to %s failed: %s", pth, e)
        state["mec"]["ipe_subscriptions"] = len(done)
        time.sleep((MS.get("ipe") or {}).get("discover_s", 5.0))


def mec_services_loop():
    """location_source: direct - poll the MEC APIs."""
    from edgeguard.mec_services import LocationClient, RnisClient
    loc = LocationClient(MS["base_url"], MS.get("location_api", "location/v3"), frame=_frame())
    rnis = RnisClient(MS["base_url"], MS.get("rnis_api", "rni/v2"))
    last_rnis, last_fix = 0.0, {}
    while True:
        now = time.monotonic()
        try:
            for u in loc.all_users():
                key = (u.get("address"), json.dumps(u.get("timestamp"), sort_keys=True),
                       json.dumps(u.get("locationInfo"), sort_keys=True))
                if last_fix.get(key[0]) == key:
                    continue                       # same fix as last poll: not a new measurement
                last_fix[key[0]] = key
                handle_mec_location(u)
        except Exception as e:
            log.debug("location query failed: %s", e)
        if now - last_rnis >= MS.get("rnis_poll_s", 1.0):
            last_rnis = now
            try:
                for c in rnis.cells(MS.get("cell_id")):
                    handle_mec_cell(c)
            except Exception as e:
                log.debug("RNIS query failed: %s", e)
        time.sleep(MS.get("poll_s", 0.25))


MAX_SKEW_MS = MEC.get("max_clock_skew_ms", 5000)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def valid_sample(p: dict) -> bool:
    if not isinstance(p.get("id"), str) or not p["id"] or not _num(p.get("x")) or not _num(p.get("y")):
        return False
    if p.get("kind") == "forklift":
        for k in ("speed", "heading", "yaw_rate"):
            if p.get(k) is not None and not _num(p[k]):
                return False
    return True


def handle_sample(p: dict):
    rx = now_ms()
    kind = p.get("kind")
    if kind == "camera":
        return handle_camera(p, rx)
    if kind not in ("worker", "forklift"):
        return
    if not valid_sample(p):
        state["input"]["bad"] += 1
        return
    ts = p.get("ts")
    if not _num(ts) or abs(rx - ts) > MAX_SKEW_MS:     # device clock not synced (NTP lost?): use arrival
        if _num(ts):
            state["input"]["clock_skew"] += 1
        ts = rx
        p = {**p, "ts": rx}
    t = ts / 1000.0
    meas = {"x": p["x"], "y": p["y"], "src_ts": p.get("ts"),
            "pos_sigma": p.get("pos_sigma"), "source": p.get("source", "uwb")}
    if kind == "forklift":
        meas.update(speed=p.get("speed"), heading=p.get("heading"), yaw_rate=p.get("yaw_rate"))
        rt = p.get("route")                        # planned waypoints from the fleet system (optional)
        if isinstance(rt, list) and 0 < len(rt) <= 30 and all(
                isinstance(q, (list, tuple)) and len(q) == 2 and all(_num(v) for v in q) for q in rt):
            meas["route"] = [tuple(map(float, q)) for q in rt]
    with lock:
        state["rx"] += 1
        if p.get("ts"):
            state["ingest_ms"].append(rx - p["ts"])
        if engine.update(Track, p["id"], kind, t, **meas) is False:
            state["input"]["late"] += 1                # out-of-order sample, the track kept the newer one
            return
        evaluate_and_alert(p.get("ts"), rx, only=p["id"])
        if rate_ctl is not None:
            control_rates()


# Adaptive reporting rate (edgeguard/rate_control.py): far devices report at 2 Hz.
RC = CFG.get("rate_control") or {}
rate_ctl = None
state["rates"] = {"fast": 0, "slow": 0, "commands": 0}
if RC.get("enabled"):
    from edgeguard.rate_control import RateController
    rate_ctl = RateController(**{k: v for k, v in RC.items() if k not in ("enabled", "period_s", "heartbeat_s", "refresh_s")})


def control_rates():
    """Caller holds `lock`. Rate changes go out at once; the full map rides on the heartbeat."""
    now = time.monotonic()
    if now - state.get("rc_last", 0) < RC.get("period_s", 0.3):
        return
    state["rc_last"] = now
    changes = rate_ctl.update(engine.tracks.values(), now)
    if changes:
        post("control", {"ts": now_ms(), "rates": changes})
        state["rates"] = {**rate_ctl.counts(), "commands": state["rates"]["commands"] + 1}


hb_now = threading.Event()                     # set on HA take-over: send a heartbeat at once


def heartbeat():
    """<ae>/control heartbeat every heartbeat_s (1 s) (edgeguard/device_policy.py): devices use it to
    tell 'MEC alive, alert over' from 'MEC silent' (forklifts then crawl), and it re-sends
    the full rate map so a lost rate command heals itself.  Written at lower priority than
    alerts, so a heartbeat that arrives also means no alert is waiting behind it."""
    while True:
        hb_now.wait(RC.get("heartbeat_s", 1.0))
        hb_now.clear()
        with lock:
            rates = dict(rate_ctl.rate) if rate_ctl is not None else {}
        post("control", {"ts": now_ms(), "hb": True, "rates": rates})


threading.Thread(target=heartbeat, daemon=True).start()


CAM = CFG.get("camera") or {}
state["untagged_seq"] = 0
state["camera"] = {"frames": 0, "matched": 0, "untagged": 0}


def handle_camera(p: dict, rx: int):
    """Fuse camera person detections with the tag tracks.

    A detection near a tagged worker is the same person (the tag already covers
    them).  Anyone else is a worker without a working tag: they get an
    `untagged_N` track so forklift alerts still fire (they cannot be vibrated)."""
    gate = CAM.get("fuse_gate_m", 1.5)
    t = p.get("ts", rx) / 1000.0
    now = time.monotonic()
    with lock:
        state["rx"] += 1
        state["camera"]["frames"] += 1
        tagged = [tr for tr in engine.tracks.values()
                  if tr.kind == "worker" and tr.x is not None and not tr.id.startswith("untagged_")
                  and now - getattr(tr, "uwb_seen", 0) < 1.0]
        untagged = [tr for tr in engine.tracks.values()
                    if tr.id.startswith("untagged_") and tr.x is not None and now - tr.last_seen < 2.0]
        used = set()
        for d in p.get("persons", []):
            x, y = d["x"], d["y"]
            if any(math.hypot(tr.pos[0] - x, tr.pos[1] - y) < gate for tr in tagged):
                state["camera"]["matched"] += 1
                continue
            best = min((tr for tr in untagged if tr.id not in used),
                       key=lambda tr: math.hypot(tr.pos[0] - x, tr.pos[1] - y), default=None)
            if best is not None and math.hypot(best.pos[0] - x, best.pos[1] - y) < 2.0:
                tid = best.id
            else:
                state["untagged_seq"] += 1
                tid = f"untagged_{state['untagged_seq']}"
                state["camera"]["untagged"] += 1
            used.add(tid)
            engine.update(Track, tid, "worker", t, x=x, y=y, src_ts=p.get("ts"),
                          pos_sigma=CAM.get("pos_sigma", 0.4), source="camera")
        evaluate_and_alert(p.get("ts"), rx)


from edgeguard.nearmiss import NearMissTracker   # noqa: E402
from edgeguard.worker_cue import WaitCue          # noqa: E402
NM = CFG.get("nearmiss") or {}
nearmiss = NearMissTracker(threshold_m=NM.get("threshold_m", 2.0), cell_m=NM.get("cell_m", 1.0))


def record_near_miss(ev):
    if ev:
        post("nearmiss", ev)
        to_cloud("nearmiss", ev)
        log.info("NEAR MISS %s-%s %.2f m at (%.1f, %.1f)%s", ev["worker"], ev["forklift"], ev["d_min"],
                 ev["x"], ev["y"], "" if ev["alerted"] else " - no alert before")


def evaluate_and_alert(src_ts, rx, only=None):
    """Assess the pairs touched by the new sample and emit alerts; caller holds `lock`."""
    risks = engine.evaluate(only=only)
    now = time.time()
    for r in risks:
        key = (r.worker, r.forklift)
        w_t, f_t = engine.tracks.get(r.worker), engine.tracks.get(r.forklift)
        if w_t is not None and f_t is not None and w_t.x is not None and f_t.x is not None:
            mid = ((w_t.pos[0] + f_t.pos[0]) / 2, (w_t.pos[1] + f_t.pos[1]) / 2)
            record_near_miss(nearmiss.observe(key, r.range, mid, now, f_t.speed, getattr(r, "occluded", False), r.level))
        st = state["pairs"].setdefault(key, {"alert": AlertState()})
        w_tr, f_tr = engine.tracks.get(r.worker), engine.tracks.get(r.forklift)
        others = [t_ for t_ in engine.tracks.values() if t_.kind == "forklift" and t_.x is not None]
        ev, actions = decide(st["alert"], r, w_tr, f_tr, engine.cfg, now, state["network"]["congested"], others)
        st["risk"] = r
        if ev:
            # mirror of the worker's tag (edgeguard/worker_cue.py) for the dashboard: WAIT / STEP ASIDE / GO
            cue = state["worker_cue"].setdefault(r.worker, WaitCue())
            cue.on_alert(now, ev, bool((actions or {}).get(r.worker, {}).get("vibrate")),
                         r.level >= 3, src=r.forklift)
            if ev == "aside":
                state["worker_aside"][r.worker] = now
            untagged = r.worker.startswith("untagged_")
            alert = {
                "event": ev, "level": LEVELS[r.level],
                "worker": r.worker, "forklift": r.forklift,
                "actions": actions,
                "reason": r.reason + (" (person seen by camera, no tag)" if untagged else ""),
                "metrics": r.to_dict(),
                "pos": {k: [round(v, 2) for v in engine.tracks[k].pos] for k in (r.worker, r.forklift)
                        if k in engine.tracks and engine.tracks[k].x is not None},
                "src_ts": src_ts, "mec_rx_ts": rx, "mec_tx_ts": now_ms(),
            }
            post("alert", alert)
            if ev in ("wait", "release", "aside"):     # worker WAIT keep-alive / GO / STEP ASIDE (edgeguard/worker_cue.py)
                state["worker_cues"][ev] += 1
                continue
            to_cloud("alert", alert)
            state["alerts_sent"] += 1
            state["alert_log"].appendleft({k: alert[k] for k in
                                           ("event", "level", "worker", "forklift", "reason",
                                            "mec_tx_ts")} | {"speed_scale": r.speed_scale})
            log.info("ALERT %s %s %s-%s: %s", ev, alert["level"], r.worker, r.forklift, alert["reason"])
    hz = MEC.get("risk_publish_hz", 2)
    if risks and now - state["last_risk_pub"] >= 1.0 / hz:
        state["last_risk_pub"] = now
        summary = {"ts": now_ms(), "pairs": [s_["risk"].to_dict() for s_ in state["pairs"].values()
                                             if "risk" in s_ and s_["risk"].level > 0]}
        post("risk", summary)
        if now - state.get("last_cloud_risk", 0) >= 1.0 / CLOUD.get("risk_hz", 1):
            state["last_cloud_risk"] = now
            to_cloud("risk", summary)


GC_S = MEC.get("track_gc_s", 30.0)


def gc_once(now=None):
    """Forget tracks silent for GC_S and their pairs (camera `untagged_N` ids, devices that left).
    Without this the track and pair tables grow for ever on a long-running host."""
    now = time.monotonic() if now is None else now
    with lock:
        gone = [k for k, t in engine.tracks.items() if now - getattr(t, "last_seen", now) > GC_S]
        for k in gone:
            del engine.tracks[k]
        for key in [k for k in state["pairs"] if k[0] in gone or k[1] in gone]:
            del state["pairs"][key]
        if rate_ctl is not None:
            for k in gone:
                for d in (rate_ctl.rate, rate_ctl.far_since):
                    if isinstance(d, dict):
                        d.pop(k, None)
        state["gc"]["tracks_removed"] += len(gone)
        live = {(w, f) for w, t in engine.tracks.items() if t.kind == "worker"
                for f, u in engine.tracks.items() if u.kind == "forklift"
                and now - getattr(t, "last_seen", now) <= 2.0 and now - getattr(u, "last_seen", now) <= 2.0}
        for ev in nearmiss.sweep(live):
            record_near_miss(ev)
    return gone


def housekeeping():
    """Every 10 s: GC; every 60 s: make sure the CSE still notifies us (a CSE restored without its
    database, or a subscription removed after failed notifications, would silently stop the feed)."""
    cl = config.client(CFG)
    last_sub = 0.0 if not HA.get("enabled") else -1e9   # HA: subscribe right away (second instance)
    state["subs"] = {"checks": 0, "repaired_errors": 0}
    while True:
        time.sleep(10.0)
        try:
            gc_once()
        except Exception as e:
            log.warning("gc failed: %s", e)
        if not MEC.get("subscription_watchdog", True) or time.monotonic() - last_sub < MEC.get("subscription_check_s", 60):
            continue
        last_sub = time.monotonic()
        state["subs"]["checks"] += 1
        for path in (list(PATHS["workers"].values()) + list(PATHS["forklifts"].values())
                     + list(PATHS["cameras"].values()) + list(PATHS.get("relay", {}).values())
                     + list(PATHS.get("status", {}).values())):
            try:   # each HA instance owns its own subscription (rn), so neither overwrites the other's URL
                cl.create_subscription(path, MEC.get("subscription_rn", "sub_mec"), [MEC["notify_url"]])
            except Exception as e:
                state["subs"]["repaired_errors"] += 1
                log.debug("subscription check %s: %s", path, e)


app = FastAPI(title="EdgeGuard MEC App")


@app.on_event("startup")
def _start_housekeeping():
    threading.Thread(target=housekeeping, daemon=True).start()


@app.on_event("startup")
def _start_ha():
    global lease
    if HA.get("enabled"):
        from edgeguard.ha import Lease
        cl = config.client(CFG)
        try:
            cl.create_container(PATHS["ae"], "mec_lease", mni=20)
        except Exception as e:
            log.warning("lease container: %s", e)
        lease = Lease(cl, PATHS["mec_lease"], INSTANCE, HA.get("lease_s", 0.6), HA.get("renew_s", 0.2),
                      on_change=lambda leader: leader and hb_now.set()).start()
        log.info("HA enabled: instance %s", INSTANCE)


@app.on_event("startup")
def _start_mec_services():
    if MS.get("enabled"):
        src = MS.get("location_source", "cse")
        threading.Thread(target=ipe_watch if src == "cse" else mec_services_loop, daemon=True).start()


_GROUP = {"worker": "workers", "forklift": "forklifts", "camera": "cameras"}


def _count_in(payload):
    """Notifications per device container (dashboard oneM2M panel)."""
    if payload.get("relay") in PATHS.get("relay", {}):
        src = PATHS["relay"][payload["relay"]]
    else:
        src = PATHS.get(_GROUP.get(payload.get("kind"), ""), {}).get(payload.get("id"))
    if src:
        state["m2m"]["in"][src] = state["m2m"]["in"].get(src, 0) + 1


def process_notification(body):
    kind, payload = parse_notification(body)
    if kind == "cin" and isinstance(payload, dict):
        _count_in(payload)
    if kind == "cin" and isinstance(payload, dict) and payload.get("kind") == "ack":
        # a real device confirms what its actuators do (firmware HIL mode: <device>/status)
        state["acks"][payload.get("id", "?")] = {**payload, "rx": time.time()}
        return
    if kind == "cin" and isinstance(payload, dict):
        if is_mec_location(payload):
            handle_mec_location(payload)
        elif is_mec_cell(payload):
            handle_mec_cell(payload)
        else:
            handle_sample(payload)


@app.post("/notify")
async def notify(req: Request):
    """Always answers 2000: a CSE that gets errors back may drop the subscription.  The risk
    engine runs in the thread pool so a slow evaluation never blocks the event loop."""
    try:
        body = await req.json()
        await run_in_threadpool(process_notification, body)
    except Exception as e:                            # malformed JSON or a bad sample
        state["input"]["bad"] += 1
        log.warning("bad notification: %s", e)
    return Response(status_code=200, headers={"X-M2M-RSC": "2000"})


def publisher_status():
    pub = state["publisher"]
    age = None if pub["last_ok"] is None else round(time.monotonic() - pub["last_ok"], 1)
    return {**{k: v for k, v in pub.items() if k != "last_ok"}, "last_ok_age_s": age, "backlog": outbox.qsize()}


@app.get("/health")
def health():
    ing = sorted(state["ingest_ms"])
    pub = publisher_status()
    # degraded: the CSE has not accepted a write for 5 s although we have been trying
    degraded = pub["failed"] > 0 and (pub["last_ok_age_s"] is None or pub["last_ok_age_s"] > 5)
    return {"ok": True, "degraded": degraded, "method": engine.method, "samples": state["rx"],
            "ha": None if lease is None else {"instance": INSTANCE, "leader": lease.leader, **lease.stats},
            "publisher": pub, "input": state["input"], "tracks": len(engine.tracks), "gc": state["gc"],
            "alerts_sent": state["alerts_sent"], "worker_cues": state["worker_cues"], "cloud": state["cloud"],
            "network": state["network"], "location_fixes": state["location_fixes"], "mec": state["mec"],
            "camera": state["camera"], "rates": state["rates"],
            "ingest_ms_median": ing[len(ing) // 2] if ing else None}


def _paths(w, f):
    """Predicted paths for the dashboard (same predictors as the risk engine)."""
    from edgeguard.predict import CVPredictor, CTRVPredictor
    from edgeguard.risk import _heading
    times = [i * 0.25 for i in range(13)]                  # 0 .. 3 s
    pw = None
    if engine.method == "guidance_lstm":
        from edgeguard.learned import predictor_or_none
        pw = predictor_or_none(w, f)
    pw = pw or CVPredictor(w.pos, w.vel)
    pf = CTRVPredictor(f.pos, f.speed, _heading(f), f.yaw_rate)
    rnd = lambda pts: [[round(x, 2), round(y, 2)] for x, y in pts]   # noqa: E731
    return rnd(pw.positions(times)), rnd(pf.positions(times))


@app.get("/state")
def snapshot():
    with lock:
        now = time.monotonic()
        tracks = {k: {"kind": t.kind, "pos": [round(v, 2) for v in t.pos],
                      "source": getattr(t, "source", "uwb"),
                      "vel": [round(v, 2) for v in t.vel],
                      "stale": now - getattr(t, "last_seen", now) > 2.0}
                  for k, t in engine.tracks.items() if t.x is not None}
        pairs = []
        for (wid, fid), s_ in state["pairs"].items():
            if "risk" not in s_:
                continue
            d = s_["risk"].to_dict()
            w, f = engine.tracks.get(wid), engine.tracks.get(fid)
            if any(t_ is None or t_.x is None or now - getattr(t_, "last_seen", now) > 2.0 for t_ in (w, f)):
                continue                             # one side went silent: drop the pair card
            if True:
                d["worker_path"], d["forklift_path"] = _paths(w, f)
            pairs.append(d)
        ing = sorted(state["ingest_ms"])
        stats = {"samples": state["rx"], "alerts_sent": state["alerts_sent"],
                 "ingest_ms_median": ing[len(ing) // 2] if ing else None,
                 "method": engine.method, "r_safe": engine.cfg.r_safe,
                 "network": state["network"], "location_fixes": state["location_fixes"]}
        cues = {}
        for wid, c in state["worker_cue"].items():
            wall = time.time()
            if c.led(wall):
                cues[wid] = {"state": "ASIDE" if wall - state["worker_aside"].get(wid, -1e9) < 3.0 else "WAIT",
                             "by": sorted(c.holds)}
            elif c.go_at is not None and wall - c.go_at < 2.0:
                cues[wid] = {"state": "GO", "by": []}
        m2m = {"devices": {d: {"ae": PATHS["device_ae"].get(d), "data": path,
                               "notifications": state["m2m"]["in"].get(path, 0)}
                           for g in ("workers", "forklifts", "cameras") for d, path in PATHS[g].items()},
               "mec": {"ae": PATHS["ae"], "out": {k: state["m2m"]["out"].get(PATHS[k], 0)
                                                  for k in ("alert", "control", "risk", "nearmiss")}},
               "cse": CFG["cse"]["cse_rn"]}
        acks = {d: a for d, a in state["acks"].items() if time.time() - a["rx"] < 10}
        return {"tracks": tracks, "pairs": pairs, "alerts": list(state["alert_log"]), "cues": cues,
                "m2m": m2m, "acks": acks,
                "obstacles": [list(r) for r in SITEMAP.rects],
                "stats": stats, "server_ms": now_ms()}


@app.get("/nearmiss")
def near_misses():
    """Measured close passes: heat-map cells, hotspots with a suggested fix, latest events."""
    with lock:
        return nearmiss.summary()


@app.get("/metrics")
def metrics():
    """Prometheus text format (scrape with Prometheus / Grafana)."""
    pub = publisher_status()
    ing = sorted(state["ingest_ms"])
    rows = [("edgeguard_samples_total", state["rx"]), ("edgeguard_alerts_total", state["alerts_sent"]),
            ("edgeguard_tracks", len(engine.tracks)), ("edgeguard_pairs", len(state["pairs"])),
            ("edgeguard_publish_ok_total", pub["ok"]), ("edgeguard_publish_failed_total", pub["failed"]),
            ("edgeguard_publish_dropped_stale_total", pub["dropped_stale"]),
            ("edgeguard_publish_dropped_full_total", pub["dropped_full"]), ("edgeguard_outbox_backlog", pub["backlog"]),
            ("edgeguard_input_bad_total", state["input"]["bad"]), ("edgeguard_input_late_total", state["input"]["late"]),
            ("edgeguard_input_clock_skew_total", state["input"]["clock_skew"]),
            ("edgeguard_mec_location_fixes_total", state["location_fixes"]),
            ("edgeguard_ingest_ms_median", ing[len(ing) // 2] if ing else 0),
            ("edgeguard_network_congested", int(state["network"]["congested"])),
            ("edgeguard_near_miss_total", nearmiss.total),
            ("edgeguard_ha_leader", int(is_leader())),
            ("edgeguard_near_miss_unalerted", sum(1 for e in nearmiss.events if not e["alerted"]))]
    body = "".join(f"{k} {v}\n" for k, v in rows)
    return Response(body, media_type="text/plain; version=0.0.4")


@app.get("/")
def dashboard():
    return FileResponse(os.path.join(STATIC, "dashboard.html"))


@app.get("/tag")
def phone_tag():
    """A phone as a worker tag: http://<mec-host>:9090/tag?worker=worker_01 (vibrates, WAIT / STEP ASIDE / GO)."""
    return FileResponse(os.path.join(STATIC, "tag.html"))


@app.get("/cue")
def worker_cue_state(worker: str):
    """What this worker's tag shows now (the MEC-side mirror of the tag's cue)."""
    with lock:
        c = state["worker_cue"].get(worker)
        wall = time.time()
        if c is not None and c.led(wall):
            st = "ASIDE" if wall - state["worker_aside"].get(worker, -1e9) < 3.0 else "WAIT"
        elif c is not None and c.go_at is not None and wall - c.go_at < 2.0:
            st = "GO"
        else:
            st = "IDLE"
        return {"worker": worker, "state": st, "go_at": None if c is None else c.go_at}


@app.post("/ack")
async def phone_ack(req: Request):
    """Confirmation from a phone tag (it is not a oneM2M device; real boards confirm in <device>/status)."""
    b = await req.json()
    dev = str(b.get("id", ""))[:40]
    with lock:
        state["acks"][dev + "@phone"] = {"id": dev, "kind": "ack", "hw": "phone", "state": str(b.get("state", ""))[:20],
                                         "rx": time.time()}
    return {"ok": True}
