"""Zone broadcast with oneM2M <group> fan-out, delivered to tags behind NAT through <pollingChannel>.

A zone-wide message (a forklift entering a pedestrian zone, a blind-corner caution, stop-all) must reach
every tag in that zone at once.  Instead of looping over tags in the application, the MEC app keeps one
oneM2M <group> per zone whose members are the `alerts` containers of the tags currently in it, and posts
ONE contentInstance to <group>/fopt: the CSE fans it out to every member.

  <dev> (tag AE, rr=false: no inbound connection needed)
    alerts            CNT   the MEC app may create contentInstances here and nothing else (chty 4)
    pch               pollingChannel: notifications for the tag wait here
    alerts/sub_self   SUB   nu = the tag's own AE-ID -> notifications go to its pollingChannel
  EdgeGuard/zone_<zone>    GRP   mid = alerts containers of the tags in that zone (updated as they move)

The tag long-polls <dev>/pch/pcu and gets each notification as soon as the CSE has it.
"""
from __future__ import annotations

import json
import threading
import time

import requests

from .onem2m import ALL_OPS, CREATE, RETRIEVE, OneM2MClient, OneM2MError, decode_con

TY_GRP, TY_PCH = 9, 15


def setup_tag_inbox(dc: OneM2MClient, dev: str, writer: str, polling=True):
    """On the tag's own AE (client acting as the tag): alerts container, ACP letting `writer` (the MEC
    app) create contentInstances there only, and - for a tag behind NAT - a pollingChannel plus a
    subscription whose notifications go to it."""
    dc.create_container(dev, "alerts", mni=20)
    acp = dc.create_acp(dev, f"acp_alerts_{dev}", [([dc.origin], ALL_OPS), ([writer], CREATE | RETRIEVE, (4,))],
                        [dc.origin])
    dc.set_acpi(f"{dev}/alerts", f"{dev}/acp_alerts_{dev}", acp.get("ri"))
    if polling:
        dc.request("POST", dev, TY_PCH, {"m2m:pch": {"rn": "pch"}}, ok_conflict=True)
        aei = (dc.request("GET", dev) or {}).get("m2m:ae", {}).get("aei") or dc.origin
        dc.create_subscription(f"{dev}/alerts", "sub_self", [aei], net=(3,))
    return acp


class PollingReceiver:
    """Tag side: long-polls its pollingChannel and hands each new alert to `on_alert(content, t_rx)`."""

    def __init__(self, dc: OneM2MClient, dev: str, on_alert, timeout=10.0):
        self.dc, self.dev, self.on_alert, self.timeout = dc, dev, on_alert, timeout
        self.stop, self.errors = threading.Event(), 0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self):
        url = self.dc.url(f"{self.dev}/pch/pcu")
        while not self.stop.is_set():
            try:
                r = requests.get(url, timeout=self.timeout + 5,
                                 headers={"X-M2M-Origin": self.dc.origin, "X-M2M-RI": f"poll{time.time()}",
                                          "X-M2M-RVI": self.dc.rvi, "Accept": "application/json"})
                if r.status_code == 200 and r.content:
                    body = r.json()
                    for rqp in body.get("m2m:agrp") or [body.get("m2m:rqp") or {}]:   # several may be queued
                        self._handle(rqp, url)
                elif r.status_code >= 400 and r.status_code != 404:
                    self.errors += 1
                    time.sleep(0.2)
            except requests.RequestException:
                self.errors += 1
                time.sleep(0.2)


    def _handle(self, rqp, url):
        rep = (((rqp.get("pc") or {}).get("m2m:sgn") or {}).get("nev") or {}).get("rep") or {}
        cin = rep.get("m2m:cin")
        if cin is not None:
            self.on_alert(decode_con(cin.get("con")), time.time())
        if rqp.get("rqi"):
            # The CSE treats a notification over a pollingChannel as a request and waits (up to its
            # request expiration) for the response, sent back through the same <pollingChannelURI>.
            try:
                requests.post(url, timeout=3, data=json.dumps({"m2m:rsp": {
                    "fr": self.dc.origin, "rqi": rqp["rqi"], "rvi": self.dc.rvi, "rsc": 2000}}),
                    headers={"X-M2M-Origin": self.dc.origin, "X-M2M-RI": f"rsp{time.time()}",
                             "X-M2M-RVI": self.dc.rvi, "Content-Type": "application/json"})
            except requests.RequestException:
                self.errors += 1


class ZoneGroups:
    """MEC app side: one <group> per zone, membership follows the tags, one fan-out request per message."""

    def __init__(self, c: OneM2MClient, ae: str, zones: dict):
        """zones: {name: (xmin, ymin, xmax, ymax)} in the site frame."""
        self.c, self.ae, self.zones = c, ae, zones
        self.members: dict[str, set] = {z: set() for z in zones}
        self.inbox: dict[str, str] = {}               # tag -> path of its alerts container
        self.sent = 0

    def setup(self):
        """Create the zone groups (idempotent).  A group that had to be (re)created - first start, or the
        AE was reset - starts empty, so the next update() rewrites its members.  Returns those zones."""
        made = []
        for z in self.zones:
            r = self.c.request("POST", self.ae, TY_GRP,
                               {"m2m:grp": {"rn": self.rn(z), "mt": 3, "mid": [], "mnm": 200, "csy": 1}},
                               ok_conflict=True)
            if r is not None:
                self.members[z] = set()
                made.append(z)
        return made

    @staticmethod
    def rn(zone):
        return f"zone_{zone}"

    def register_tag(self, dev, inbox=None):
        self.inbox[dev] = inbox or f"{dev}/alerts"

    def zone_of(self, x, y):
        for z, (x0, y0, x1, y1) in self.zones.items():
            if x0 <= x < x1 and y0 <= y < y1:
                return z
        return None

    def update(self, positions: dict):
        """positions: {tag: (x, y)}.  Rewrites the member list of every zone whose membership changed."""
        new = {z: set() for z in self.zones}
        for dev, (x, y) in positions.items():
            z = self.zone_of(x, y)
            if z and dev in self.inbox:
                new[z].add(dev)
        changed = [z for z in self.zones if new[z] != self.members[z]]
        for z in changed:
            mid = [f"{self.c.cse_rn}/{self.inbox[d]}" for d in sorted(new[z])]
            self.c.request("PUT", f"{self.ae}/{self.rn(z)}", None, {"m2m:grp": {"mid": mid}})
            self.members[z] = new[z]
        return changed

    def broadcast(self, zone, message: dict):
        """One request; the CSE creates the contentInstance in every member.  Returns how many accepted."""
        if not self.members.get(zone):
            return 0
        res = self.c.request("POST", f"{self.ae}/{self.rn(zone)}/fopt", 4, {"m2m:cin": {"con": message}}) or {}
        rsps = (res.get("m2m:agr") or {}).get("m2m:rsp") or []
        self.sent += 1
        return sum(1 for r in rsps if int(r.get("rsc", 0)) in (2000, 2001))
