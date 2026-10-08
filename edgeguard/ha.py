"""Active-standby MEC app (high availability) with a lease in the CSE.

Two MEC app instances receive the same device notifications (each has its own subscription), so
both keep warm tracks and alert state.  Only the *leader* writes alerts, heartbeats, risk
summaries and near misses.  Leadership is a lease: the leader writes {id, seq} to <AE>/mec_lease
every `renew_s`; an instance that sees no new lease entry for `lease_s` takes over by writing its
own entry and confirming it is the latest.  Staleness is judged on the local monotonic clock
(time since the lease entry last changed), so host clocks need not agree.

Take-over <= lease_s + renew_s (default 0.6 + 0.2 s) and the new leader sends a control
heartbeat at once, so the heartbeat gap seen by devices stays below 1 s (heartbeat period) +
0.8 s, under the 2 s after which a forklift falls back to its local rule
(edgeguard/device_policy.py LOCAL_AFTER_S).
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("edgeguard.ha")


class Lease:
    def __init__(self, client, path, instance_id, lease_s=0.6, renew_s=0.2, on_change=None):
        self.c, self.path, self.id = client, path, instance_id
        self.lease_s, self.renew_s = lease_s, renew_s
        self.leader = False
        self.seq = 0
        self.seen = None                 # (holder, seq) last observed
        self.seen_at = time.monotonic()
        self.on_change = on_change
        self.stats = {"took_over": 0, "lost": 0, "errors": 0, "holder": None}

    def _read(self):
        con = self.c.latest(self.path)
        return (con.get("id"), con.get("seq")) if isinstance(con, dict) else None

    def _write(self):
        self.seq += 1
        self.c.create_cin(self.path, {"id": self.id, "seq": self.seq, "ts": int(time.time() * 1000)})

    def step(self, now=None):
        now = time.monotonic() if now is None else now
        try:
            cur = self._read()
        except Exception:
            cur, self.stats["errors"] = None, self.stats["errors"] + 1
        if cur is not None and cur != self.seen:
            self.seen, self.seen_at = cur, now
        holder = self.seen[0] if self.seen else None
        self.stats["holder"] = holder
        was = self.leader
        try:
            if holder == self.id:
                self._write()                               # renew
                self.leader = True
            elif self.seen is None or now - self.seen_at > self.lease_s:
                self._write()                               # stale or empty: try to take it
                cur = self._read()
                self.leader = cur is not None and cur[0] == self.id
                if cur is not None:
                    self.seen, self.seen_at = cur, now
            else:
                self.leader = False
        except Exception as e:
            self.stats["errors"] += 1
            log.debug("lease step failed: %s", e)
            self.leader = False if holder != self.id else self.leader
        if self.leader != was:
            self.stats["took_over" if self.leader else "lost"] += 1
            log.warning("HA: %s is now %s", self.id, "LEADER" if self.leader else "standby")
            if self.on_change:
                self.on_change(self.leader)
        return self.leader

    def run(self):
        while True:
            self.step()
            time.sleep(self.renew_s)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        return self
