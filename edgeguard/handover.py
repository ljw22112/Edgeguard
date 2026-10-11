"""CSE handover between the MN-CSEs of warehouse zones (service continuity for moving devices).

A forklift module (or worker tag) keeps its SDT twin (edgeguard/sdt.py) on the MN-CSE of the zone it
is in - the MEC host of that zone.  When it crosses into another zone, or its serving CSE stops
answering, the device moves its oneM2M presence, make-before-break:

  1. target selection  zone that contains the position (hysteresis: hand over only when the position
                       is `hysteresis` metres inside the new zone), or - availability - the nearest
                       zone whose CSE answers
  2. prepare (in the background, samples keep flowing to the source):
       state           module values read from the source twin (kinematics, speed limit / cue, battery)
       security        AE, twin and ACP rebuilt on the target with the same rules
       subscriptions   every subscription on the source twin's modules re-created on the target with
                       the same notification URIs, so subscribers keep receiving without doing anything
       announcement    the new AE is announced to the IN-CSE (AEAnnc lnk -> serving CSE)
  3. switch            the next sample goes to the target
  4. home record       <IN-CSE>/<dev>/serving gets {serving CSE, zone, reason, timings}: applications
                       resolve (or subscribe to) the serving CSE there
  5. release           the source AE is deleted after a grace period (in-flight notifications)

Timings and the sample log let tools/handover_demo.py measure the service interruption and data loss.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import requests

from . import sdt
from .onem2m import OneM2MClient, OneM2MError, TY_SUB


@dataclass
class Zone:
    name: str
    base_url: str
    cse_rn: str
    cse_id: str
    rect: tuple            # (xmin, ymin, xmax, ymax), site frame (m)

    def contains(self, x, y, margin=0.0):
        x0, y0, x1, y1 = self.rect
        return x0 + margin <= x < x1 - margin and y0 + margin <= y < y1 - margin

    def distance(self, x, y):
        x0, y0, x1, y1 = self.rect
        dx = max(x0 - x, 0.0, x - x1)
        dy = max(y0 - y, 0.0, y - y1)
        return (dx * dx + dy * dy) ** 0.5


def zones_from_config(hcfg):
    return [Zone(z["name"], z["base_url"], z["cse_rn"], z["cse_id"], tuple(z["rect"])) for z in hcfg["zones"]]


@dataclass
class HandoverEvent:
    device: str
    source: str
    target: str
    reason: str
    t_start: float
    t_switch: float = 0.0
    prep_ms: float = 0.0
    subscriptions: int = 0
    state_keys: list = field(default_factory=list)
    released: bool = False
    error: str = ""


class HandoverClient:
    """Device-side oneM2M presence that follows the device across zone MN-CSEs."""

    def __init__(self, cfg, dev, kind, origin, zones, home=None, readers=(), hysteresis=1.0,
                 fail_limit=3, grace_s=0.5, rvi="3", timeout=1.0, log=print, trigger="location"):
        self.cfg, self.dev, self.kind, self.origin = cfg, dev, kind, origin
        self.zones = {z.name: z for z in zones}
        self.home = home                      # OneM2MClient on the IN-CSE acting as the device
        self.readers = list(readers)
        self.hyst, self.fail_limit, self.grace = hysteresis, fail_limit, grace_s
        self.rvi, self.timeout, self.log = rvi, timeout, log
        self.serving = None                   # zone name
        self.pending = None                   # handover in preparation
        self.failures = 0
        self.events: list[HandoverEvent] = []
        self.backoff: dict = {}               # zone -> no new attempt before (after a failed preparation)
        self.sent: list[tuple] = []           # (sample ts, zone, accepted)
        self.lock = threading.Lock()
        # "location": the device decides from its own position; "network": the MEC platform decides
        # (a MEC 013 zone event delivered through the MEC-IPE calls network_trigger, docs/mobility.md)
        self.trigger = trigger

    # --- helpers -------------------------------------------------------------
    def client(self, zone):
        z = self.zones[zone]
        return OneM2MClient(z.base_url, z.cse_rn, self.origin, self.rvi, timeout=self.timeout)

    def kin_path(self):
        return sdt.kin_path(self.dev, self.kind)

    def zone_of(self, x, y):
        return next((z.name for z in self.zones.values() if z.contains(x, y)), None)

    def alive(self, zone):
        z = self.zones[zone]
        try:
            r = requests.get(f"{z.base_url}/{z.cse_rn}", timeout=self.timeout,
                             headers={"X-M2M-Origin": self.origin, "X-M2M-RI": "probe", "X-M2M-RVI": self.rvi})
            return r.status_code < 500
        except requests.RequestException:
            return False

    # --- lifecycle -------------------------------------------------------------
    def attach(self, x, y, reason="power-on"):
        """First registration: the zone that contains (x, y)."""
        zone = self.zone_of(x, y) or min(self.zones, key=lambda n: self.zones[n].distance(x, y))
        sdt.build_twin(self.client(zone), self.cfg, self.dev, self.kind, self.readers, zone=zone,
                       announce_to=["/" + self._in_cse_id()] if self.home else None, log=lambda *_: None)
        self.serving = zone
        self._home_record(zone, reason, None)
        self.log(f"{self.dev}: attached to {zone} ({self.zones[zone].cse_id})")
        return zone

    def _in_cse_id(self):
        return ((self.cfg.get("handover") or {}).get("in_cse_id")) or "id-in"

    def publish(self, sample):
        """Send one sample; decides and runs handovers.  Returns the zone that accepted it (or None)."""
        x, y = sample["x"], sample["y"]
        with self.lock:
            p = self.pending
            if p is not None and p["ready"].is_set():          # switch: the target is prepared
                self._switch(p)
            elif p is None and self.serving is not None and self.trigger == "location":
                cur = self.zones[self.serving]
                if not cur.contains(x, y, margin=-self.hyst):  # left the serving zone by > hysteresis
                    tgt = next((z.name for z in self.zones.values()
                                if z.name != self.serving and z.contains(x, y, margin=0.0)
                                and time.time() >= self.backoff.get(z.name, 0.0)), None)
                    if tgt:
                        self._prepare(tgt, "location")
            zone = self.serving
        try:
            self.client(zone).publish(self.kin_path(), sample)
            self.failures = 0
            self.sent.append((sample.get("ts"), zone, True))
            return zone
        except (OneM2MError, requests.RequestException) as e:
            self.sent.append((sample.get("ts"), zone, False))
            self.failures += 1
            if self.failures >= self.fail_limit and self.pending is None:
                self._failover(x, y, str(e))
            return None

    def network_trigger(self, target, reason="network"):
        """Network-side trigger: the MEC platform saw the UE attach to `target`'s access point.  Prepares
        in the background; the next publish() switches.  Returns True if a preparation started."""
        with self.lock:
            if (self.pending is not None or target == self.serving or target not in self.zones
                    or time.time() < self.backoff.get(target, 0.0)):
                return False
            self._prepare(target, reason)
            return True

    def _failover(self, x, y, why):
        """Availability trigger: the serving CSE stopped answering - nearest zone whose CSE answers.
        The source cannot be read any more: the twin is rebuilt from the device's own last state."""
        cands = sorted((n for n in self.zones if n != self.serving), key=lambda n: self.zones[n].distance(x, y))
        for n in cands:
            if self.alive(n):
                self.log(f"{self.dev}: serving CSE {self.serving} unreachable ({why[:60]}) -> {n}")
                with self.lock:
                    self._prepare(n, "availability", source_alive=False)
                return

    def _prepare(self, target, reason, source_alive=True):
        ev = HandoverEvent(self.dev, self.serving, target, reason, time.time())
        p = {"event": ev, "ready": threading.Event()}
        self.pending = p
        threading.Thread(target=self._do_prepare, args=(p, source_alive), daemon=True).start()

    def _do_prepare(self, p, source_alive):
        ev = p["event"]
        src, dst = self.client(ev.source), self.client(ev.target)
        try:
            state, subs = {}, []
            if source_alive:
                state = sdt.read_state(src, self.dev, self.kind)
                subs = self._subscriptions(src)
            ev.state_keys = sorted(state)
            acp = sdt.build_twin(dst, self.cfg, self.dev, self.kind, self.readers, zone=ev.target, state=state,
                                 announce_to=["/" + self._in_cse_id()] if self.home else None, log=lambda *_: None)
            acpi = [acp["ri"]] if acp and acp.get("ri") else []
            for parent, sub in subs:
                body = {"m2m:sub": {"rn": sub["rn"], "nu": sub["nu"], "nct": sub.get("nct", 1),
                                    **({"enc": sub["enc"]} if sub.get("enc") else {}),
                                    **({"acpi": acpi} if acpi else {})}}
                dst.request("POST", parent, TY_SUB, body, ok_conflict=True)
            if not source_alive:   # the old subscribers re-subscribe from the home record; copy what we know
                for parent, sub in self._default_subs():
                    if acpi:
                        sub["m2m:sub"]["acpi"] = acpi
                    dst.request("POST", parent, TY_SUB, sub, ok_conflict=True)
            ev.subscriptions = len(subs)
        except Exception as e:                                # keep serving from the source
            ev.error = str(e)[:200]
            self.backoff[ev.target] = time.time() + 5.0
            self.log(f"{self.dev}: handover to {ev.target} failed, retry in 5 s: {ev.error[:80]}")
        ev.prep_ms = (time.time() - ev.t_start) * 1000
        p["ready"].set()

    def _switch(self, p):
        ev = p["event"]
        self.pending = None
        self.events.append(ev)
        if ev.error:
            return
        ev.t_switch = time.time()
        old, self.serving = self.serving, ev.target
        self.failures = 0
        self._home_record(ev.target, ev.reason, ev)
        self.log(f"{self.dev}: handover {old} -> {ev.target} ({ev.reason}), prepared in {ev.prep_ms:.0f} ms, "
                 f"{ev.subscriptions} subscription(s), state {ev.state_keys}")
        threading.Thread(target=self._release, args=(old, ev), daemon=True).start()

    def _release(self, zone, ev):
        time.sleep(self.grace)
        try:
            self.client(zone).delete(self.dev)
            ev.released = True
        except Exception:
            pass

    def _subscriptions(self, c):
        """(parent path, subscription) for every subscription on the twin and its modules."""
        out = []
        twin = sdt.twin_path(self.dev, self.kind)
        for i, rn in enumerate(sdt.TWIN_MODULES[self.kind]):
            parent = twin if i == 0 else f"{twin}/{rn}"
            res = c.request("GET", parent, params={"fu": 1, "ty": TY_SUB, "lvl": 1}) or {}
            for u in res.get("m2m:uril") or []:
                s = (c.request("GET", c._rel(u)) or {}).get("m2m:sub")
                if s:
                    out.append((parent, s))
        return out

    def _default_subs(self):
        hcfg = self.cfg.get("handover") or {}
        out = []
        for url in hcfg.get("subscribers", []):
            out.append((self.kin_path(), {"m2m:sub": {"rn": "sub_app", "nu": [url], "nct": 1, "enc": {"net": [1]}}}))
        return out

    def _home_record(self, zone, reason, ev):
        if self.home is None:
            return
        z = self.zones[zone]
        con = {"device": self.dev, "zone": zone, "cse_id": z.cse_id, "poa": f"{z.base_url}/{z.cse_rn}",
               "twin": sdt.twin_path(self.dev, self.kind), "reason": reason, "ts": int(time.time() * 1000)}
        if ev is not None:
            con.update(source=ev.source, prep_ms=round(ev.prep_ms, 1), subscriptions=ev.subscriptions)
        try:
            self.home.create_cin(f"{self.dev}/serving", con)
        except Exception as e:
            self.log(f"{self.dev}: home record failed: {e}")


def setup_home(home, dev, readers):
    """Home AE of the device on the IN-CSE with its `serving` container (readers may read/subscribe)."""
    from .onem2m import ALL_OPS, RETRIEVE, DISCOVERY, NOTIFY, CREATE
    home.create_ae(dev, "Nedgeguard.home", lbl=[f"egs:id/{dev}", "egs:home"])
    home.create_container(dev, "serving", mni=50)
    acp = home.create_acp(dev, f"acp_{dev}", [([home.origin], ALL_OPS),
                                             (list(readers), RETRIEVE | DISCOVERY | NOTIFY | CREATE)],
                          [home.origin])
    home.set_acpi(f"{dev}/serving", f"{dev}/acp_{dev}", acp.get("ri"))
