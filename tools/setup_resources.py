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
        for leaf in ("risk", "alert", "control"):
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
    # adaptive reporting rate commands (MEC -> devices), see edgeguard/rate_control.py
    c.with_retry(c.create_container, p["ae"], "control")
    c.with_retry(c.create_subscription, p["control"], "sub_devices", [cfg["device_sim"]["notify_url"]])
    sec = cfg.get("security") or {}
    if sec.get("enabled"):
        apply_acps(c, cfg, p, sec)
    for i, url in enumerate(cfg.get("alert_subscribers") or []):
        c.create_subscription(p["alert"], f"sub_hw{i + 1}", [url])
        c.create_subscription(p["control"], f"sub_hw{i + 1}", [url])
        print("   alert ->", url)
    print("  ", p["risk"], ";", p["alert"], "-> devices")


def apply_acps(c, cfg, p, sec):
    """One ACP per device container: only that device (and the MEC app) may write it.
    risk / alert / control: the MEC app writes, devices may only read."""
    from edgeguard.onem2m import CREATE, RETRIEVE, DISCOVERY, ALL_OPS
    mec = cfg["cse"]["origin"]
    orig = sec.get("originators", {})
    for group in ("workers", "forklifts", "cameras"):
        for dev, path in p[group].items():
            o = orig.get(dev)
            if not o:
                continue
            acp = c.with_retry(c.create_acp, p["ae"], f"acp_{dev}",
                               [([mec], ALL_OPS), ([o], CREATE | RETRIEVE)], [mec])
            c.set_acpi(path, f"{p['ae']}/acp_{dev}", acp.get("ri"))
            print(f"   ACP {path}: write = {o}, {mec}")
    readers = [o for o in orig.values()]
    for leaf in ("risk", "alert", "control"):
        acp = c.with_retry(c.create_acp, p["ae"], f"acp_{leaf}",
                           [([mec], ALL_OPS)] + ([(readers, RETRIEVE | DISCOVERY)] if readers else []), [mec])
        c.set_acpi(p[leaf], f"{p['ae']}/acp_{leaf}", acp.get("ri"))
        print(f"   ACP {p[leaf]}: write = {mec}, read = devices")


if __name__ == "__main__":
    main()
