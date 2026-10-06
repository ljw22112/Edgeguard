"""Store-and-forward copy of risk summaries and alerts to the cloud CSE.

Runs on its own thread so a slow or broken WAN never delays local alerts.
Items that cannot be delivered stay in an ordered backlog and are retried with
exponential backoff; when the backlog is full the oldest *risk summaries* are
dropped first (alerts are kept as long as possible), so after an outage the
cloud receives the complete alert history in order.
"""
from __future__ import annotations

import collections
import logging
import threading
import time

log = logging.getLogger("edgeguard.cloud")


class CloudSync:
    def __init__(self, client, ae, capacity=5000, max_backoff=10.0):
        self.c, self.ae = client, ae
        self.capacity, self.max_backoff = capacity, max_backoff
        self.q: collections.deque = collections.deque()
        self.cv = threading.Condition()
        self.stats = {"sent": 0, "failed_attempts": 0, "dropped": 0, "backlog": 0,
                      "max_backlog": 0, "online": None}
        self._ready = False
        threading.Thread(target=self._run, daemon=True).start()

    def put(self, kind, con):
        with self.cv:
            if len(self.q) >= self.capacity:
                # drop the oldest risk summary; only if there is none, the oldest item
                for i, (k, _) in enumerate(self.q):
                    if k == "risk":
                        del self.q[i]
                        break
                else:
                    self.q.popleft()
                self.stats["dropped"] += 1
            self.q.append((kind, con))
            self.stats["backlog"] = len(self.q)
            self.stats["max_backlog"] = max(self.stats["max_backlog"], len(self.q))
            self.cv.notify()

    def _send(self, kind, con):
        if not self._ready:
            self.c.create_ae(self.ae)
            for cnt in ("risk", "alert"):
                self.c.create_container(self.ae, cnt, mni=10000)
            self._ready = True
        self.c.create_cin(f"{self.ae}/{kind}", con)

    def _run(self):
        backoff = 0.5
        while True:
            with self.cv:
                while not self.q:
                    self.cv.wait()
                kind, con = self.q[0]                    # peek: keep order on failure
            try:
                self._send(kind, con)
            except Exception as e:
                self.stats["failed_attempts"] += 1
                if self.stats["online"] is not False:
                    log.warning("cloud unreachable, buffering (%s)", e)
                self.stats["online"] = False
                self._ready = False
                time.sleep(backoff)
                backoff = min(self.max_backoff, backoff * 2)
                continue
            with self.cv:
                if self.q and self.q[0][1] is con:
                    self.q.popleft()
                self.stats["backlog"] = len(self.q)
            if self.stats["online"] is False:
                log.info("cloud reachable again, flushing backlog of %d", len(self.q))
            self.stats["online"] = True
            self.stats["sent"] += 1
            backoff = 0.5
