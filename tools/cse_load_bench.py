"""CSE load test: can the edge CSE keep up with a whole site?

N virtual devices each write one contentInstance every 100 ms (10 Hz) into
their own container; every container has a subscription to one local listener
(like the MEC app).  For each N we measure write latency and notification
latency / loss.

    python tools/cse_load_bench.py --target acme   --devices 10 25 50
    python tools/cse_load_bench.py --target mobius --devices 10 25 50
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard.onem2m import OneM2MClient, parse_notification, now_ms  # noqa: E402

TARGETS = {
    "acme": ("http://127.0.0.1:8081", "cse-mn", "CLoadTest", "3"),
    "mobius": ("http://127.0.0.1:7579", "Mobius", "SLoadTest", "2a"),
}
received = []          # (device, seq, latency_ms)
rlock = threading.Lock()


class Listener(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("X-M2M-RSC", "2000")
        self.send_header("Content-Length", "0")
        self.end_headers()
        try:
            kind, p = parse_notification(json.loads(body))
        except ValueError:
            return
        if kind == "cin" and isinstance(p, dict) and "seq" in p:
            with rlock:
                received.append((p["dev"], p["seq"], now_ms() - p["ts"]))

    def log_message(self, *a):
        pass


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1)))]


def run_level(target, n, seconds, port):
    base, rn, origin, rvi = TARGETS[target]
    admin = OneM2MClient(base, rn, origin, rvi)
    ae = f"Load{n}"
    admin.delete(ae)
    admin.create_ae(ae)
    for i in range(n):
        admin.with_retry(admin.create_container, ae, f"d{i}")
        admin.with_retry(admin.create_subscription, f"{ae}/d{i}", "sub", [f"http://127.0.0.1:{port}/n"])
    received.clear()
    write_lat, errors, sent = [], [0], [0]
    wl = threading.Lock()
    stop = time.time() + seconds

    def device(i):
        c = OneM2MClient(base, rn, origin, rvi, timeout=5)
        seq, nxt = 0, time.time() + (i % 10) * 0.01
        while time.time() < stop:
            delay = nxt - time.time()
            if delay > 0:
                time.sleep(delay)
            t = time.time()
            try:
                c.create_cin(f"{ae}/d{i}", {"dev": i, "seq": seq, "ts": now_ms()})
                with wl:
                    write_lat.append((time.time() - t) * 1000)
                    sent[0] += 1
            except Exception:
                with wl:
                    errors[0] += 1
            seq += 1
            nxt += 0.1
    th = [threading.Thread(target=device, args=(i,)) for i in range(n)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    time.sleep(2.0)                          # let notifications drain
    with rlock:
        lats = [r[2] for r in received]
        uniq = len({(r[0], r[1]) for r in received})
    admin.delete(ae)
    return {
        "target": target, "devices": n, "offered_writes_per_s": n * 10,
        "achieved_writes_per_s": round(sent[0] / seconds, 1),
        "write_errors": errors[0],
        "write_ms_p50": round(pct(write_lat, .5), 1) if write_lat else None,
        "write_ms_p95": round(pct(write_lat, .95), 1) if write_lat else None,
        "notify_ms_p50": pct(lats, .5), "notify_ms_p95": pct(lats, .95),
        "notify_delivered_pct": round(100 * uniq / max(1, sent[0]), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=TARGETS, required=True)
    ap.add_argument("--devices", type=int, nargs="+", default=[10, 25, 50])
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--port", type=int, default=9095)
    ap.add_argument("--out")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Listener)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    res = []
    for n in a.devices:
        r = run_level(a.target, n, a.seconds, a.port)
        print(json.dumps(r), flush=True)
        res.append(r)
    if a.out:
        json.dump(res, open(a.out, "w"), indent=2)
    srv.shutdown()


if __name__ == "__main__":
    main()
