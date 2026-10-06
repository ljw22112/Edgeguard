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
        c.delete(p["ae"])
        print("deleted", p["ae"])
    c.create_ae(p["ae"])
    print("AE", p["ae"])
    for group in ("workers", "forklifts", "cameras"):
        for dev, path in p[group].items():
            parent, leaf = path.rsplit("/", 1)
            c.create_container(p["ae"], dev)
            c.create_container(parent, leaf)
            c.create_subscription(path, "sub_mec", [cfg["mec"]["notify_url"]])
            print("  ", path, "-> MEC")
    c.create_container(p["ae"], "risk")
    c.create_container(p["ae"], "alert")
    c.create_subscription(p["alert"], "sub_devices", [cfg["device_sim"]["notify_url"]])
    for i, url in enumerate(cfg.get("alert_subscribers") or []):
        c.create_subscription(p["alert"], f"sub_hw{i + 1}", [url])
        print("   alert ->", url)
    print("  ", p["risk"], ";", p["alert"], "-> devices")


if __name__ == "__main__":
    main()
