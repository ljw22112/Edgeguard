"""Create the EdgeGuard oneM2M resource tree and subscriptions.

    python tools/setup_resources.py            # create (idempotent)
    python tools/setup_resources.py --reset    # delete the AE first

Tree:
  /<cse>/EdgeGuard (AE)
     worker_01/location     forklift_01/motion     camera_01/detect
     risk                   alert
  subscriptions: every location/motion/detect -> MEC app, alert -> devices
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edgeguard import config  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    cfg = config.load(a.config)
    c = config.client(cfg)
    p = config.paths(cfg)

    if a.reset:
        # delete bottom-up: some CSEs (Mobius 3) cascade asynchronously, and a child
        # name can stay reserved for a moment after its AE is gone
        for group in ("workers", "forklifts", "cameras"):
            for dev, path in p[group].items():
                c.delete(path)
                c.delete(f"{p['ae']}/{dev}")
        for leaf in ("risk", "alert"):
            c.delete(f"{p['ae']}/{leaf}")
        c.delete(p["ae"])
        time.sleep(0.5)
        print("deleted", p["ae"])
    c.create_ae(p["ae"])
    print("AE", p["ae"])
    for group in ("workers", "forklifts", "cameras"):
        for dev, path in p[group].items():
            parent, leaf = path.rsplit("/", 1)
            c.with_retry(c.create_container, p["ae"], dev)
            c.with_retry(c.create_container, parent, leaf)
            c.with_retry(c.create_subscription, path, "sub_mec", [cfg["mec"]["notify_url"]])
            print("  ", path, "-> MEC")
    c.with_retry(c.create_container, p["ae"], "risk")
    c.with_retry(c.create_container, p["ae"], "alert")
    c.with_retry(c.create_subscription, p["alert"], "sub_devices", [cfg["device_sim"]["notify_url"]])
    for i, url in enumerate(cfg.get("alert_subscribers") or []):
        c.create_subscription(p["alert"], f"sub_hw{i + 1}", [url])
        print("   alert ->", url)
    print("  ", p["risk"], ";", p["alert"], "-> devices")


if __name__ == "__main__":
    main()
