"""Entry point of a deployed EdgeGuard application instance (container image deploy/edge-app/Dockerfile).

    python -m edgeguard.edge_app --cse http://127.0.0.1:8080/cse-in --name edgeguard-risk --instance r1 \
        --host host-a1 --port 9411 --orchestrator SEGOrch

Registers its own AE, waits for the orchestrator's provisioning, processes the device data it was told to
subscribe to and writes a heartbeat (edgeguard/orchestration.py EdgeApp).  SIGTERM removes its AE.
"""
from __future__ import annotations

import argparse
import signal
import threading

from .orchestration import app_class


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cse", required=True, help="CSE base URL including the CSE name, e.g. http://host:8080/cse-in")
    for a in ("--name", "--instance", "--host", "--orchestrator"):
        ap.add_argument(a, required=True)
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args()
    base, rn = a.cse.rstrip("/").rsplit("/", 1)
    app = app_class(a.name)((base, rn), a.name, a.instance, a.host, a.port, a.orchestrator).start()
    done = threading.Event()

    def stop(*_):
        app.terminate()
        try:
            app.c.delete(app.ae)
        except Exception:
            pass
        done.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"edge app {a.name} instance {a.instance} on {a.host}, port {a.port}", flush=True)
    done.wait()


if __name__ == "__main__":
    main()
