"""Create the EdgeGuard oneM2M resource tree and subscriptions.

    python tools/setup_resources.py            # create (idempotent)
    python tools/setup_resources.py --reset    # delete the AE first

Tree (layout "device_ae", default):
  /<cse>/worker_01 (AE, originator = the tag)       /location   + acp_worker_01
  /<cse>/forklift_01 (AE, originator = the module)  /motion     + acp_forklift_01
  /<cse>/camera_01 (AE)                             /detect     + acp_camera_01
  /<cse>/EdgeGuard (AE, originator = MEC app)       /risk /alert /control /nearmiss /mec_lease
  subscriptions: every location/motion/detect -> MEC app, alert / control -> devices

Each device AE is created with the device's own originator (here on its behalf; the firmware
registers itself the same way on boot).  Its ACP lets the device do everything and the MEC app
read / subscribe / write fixes from network positioning (MEC-IPE); no other device may write it.
Positions a tag or module relays for a neighbour in a radio shadow go to its own <dev>/relay.

onem2m.data_model "sdt" (edgeguard/sdt.py, needs config/onem2m/edgeguard.fcp on the CSE): instead of
<dev>/location | motion, each tag / module gets a labelled device twin of flexContainers
(<dev>/tag | module with kinematics, cue | speedLimit, battery) and a SAREF semanticDescriptor.
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

    devices = {dev: g for g in ("workers", "forklifts", "cameras") for dev in p[g]}
    per_device = p.get("layout") == "device_ae"
    if a.reset:
        # delete bottom-up: some CSEs (Mobius 3) cascade asynchronously, and a child
        # name can stay reserved for a moment after its AE is gone
        for dev, g in devices.items():
            dc = config.device_client(cfg, dev) if per_device else c
            dc.delete(p[g][dev])
            dc.delete(p["device_ae"][dev])
        for leaf in ("risk", "alert", "control", "nearmiss", "mec_lease"):
            c.delete(f"{p['ae']}/{leaf}")
        c.delete(p["ae"])
        time.sleep(0.5)
        print("deleted", p["ae"], "and the device AEs" if per_device else "")
    c.create_ae(p["ae"], api="Nedgeguard.mec")
    print("AE", p["ae"], "(MEC app)")
    for dev, g in devices.items():
        path = p[g][dev]
        parent, leaf = path.rsplit("/", 1)
        if per_device:
            dc = config.device_client(cfg, dev)
            if dev in p.get("twin", {}):
                create_twin(dc, cfg, p, dev, g[:-1])
            else:
                dc.with_retry(dc.create_ae, dev, f"Nedgeguard.{g[:-1]}")
                dc.with_retry(dc.create_container, parent, leaf)
                device_acp(dc, cfg, p, dev, path)
            for extra in ("relay", "status"):          # D2D relay; actuator confirmations (HIL boards)
                if dev in p[extra]:
                    dc.with_retry(dc.create_container, p["device_ae"][dev], extra, mni=50)
                    dc.set_acpi(p[extra][dev], f"{p['device_ae'][dev]}/acp_{dev}")
                    c.with_retry(c.create_subscription, p[extra][dev], "sub_mec", [cfg["mec"]["notify_url"]])
        else:
            c.with_retry(c.create_container, p["ae"], dev)
            c.with_retry(c.create_container, parent, leaf)
        c.with_retry(c.create_subscription, path, "sub_mec", [cfg["mec"]["notify_url"]])
        print(f"   {path} ({'AE ' + dev if per_device else 'container'}) -> MEC")
    c.with_retry(c.create_container, p["ae"], "risk")
    c.with_retry(c.create_container, p["ae"], "nearmiss", mni=2000)   # measured close passes (edgeguard/nearmiss.py)
    c.with_retry(c.create_container, p["ae"], "mec_lease", mni=20)    # active-standby lease (edgeguard/ha.py)
    c.with_retry(c.create_container, p["ae"], "alert")
    c.with_retry(c.create_subscription, p["alert"], "sub_devices", [cfg["device_sim"]["notify_url"]])
    # adaptive reporting rate commands (MEC -> devices), see edgeguard/rate_control.py
    c.with_retry(c.create_container, p["ae"], "control")
    c.with_retry(c.create_subscription, p["control"], "sub_devices", [cfg["device_sim"]["notify_url"]])
    sec = cfg.get("security") or {}
    if sec.get("enabled"):
        apply_acps(c, cfg, p, sec, devices_done=per_device)
    for i, url in enumerate(cfg.get("alert_subscribers") or []):
        c.create_subscription(p["alert"], f"sub_hw{i + 1}", [url])
        c.create_subscription(p["control"], f"sub_hw{i + 1}", [url])
        print("   alert ->", url)
    print("  ", p["risk"], ";", p["alert"], "-> devices")


def create_twin(dc, cfg, p, dev, kind):
    """SDT device twin, created by the device itself (edgeguard/sdt.py)."""
    from edgeguard import sdt
    zone = ((cfg.get("site") or {}).get("zones") or {}).get(dev) if isinstance(cfg.get("site"), dict) else None
    ipe = (cfg.get("mec_ipe") or {}).get("origin", "SMecIpe")
    sdt.build_twin(dc, cfg, dev, kind, [cfg["cse"]["origin"], ipe], zone=zone)
    zb = (cfg.get("onem2m") or {}).get("zone_broadcast") or {}
    if kind == "worker" and zb.get("zones"):
        # alerts inbox the MEC app's zone <group> fans out to; polling channel for tags behind NAT
        from edgeguard.zones import setup_tag_inbox
        dc.with_retry(setup_tag_inbox, dc, p["device_ae"][dev], cfg["cse"]["origin"], zb.get("tag_polling", True))


def device_acp(dc, cfg, p, dev, path, tp="m2m:cnt"):
    """ACP of a device's own AE (created by the device): the device everything; the MEC app (and
    MEC-IPE) read, discover, subscribe and write fixes from network positioning; nobody else."""
    from edgeguard.onem2m import CREATE, RETRIEVE, DISCOVERY, DELETE, NOTIFY, ALL_OPS
    me, mec = config.device_origin(cfg, dev), cfg["cse"]["origin"]
    ipe = (cfg.get("mec_ipe") or {}).get("origin", "SMecIpe")
    rules = [([me], ALL_OPS), ([mec, ipe], CREATE | RETRIEVE | DISCOVERY | NOTIFY | DELETE)]
    acp = dc.with_retry(dc.create_acp, p["device_ae"][dev], f"acp_{dev}", rules, [me, mec])
    dc.set_acpi(path, f"{p['device_ae'][dev]}/acp_{dev}", acp.get("ri") if acp else None, tp=tp)
    print(f"   ACP {path}: all = {me}; read/subscribe = MEC app; others: none")
    return acp


def apply_acps(c, cfg, p, sec, devices_done=False):
    """Single-AE layout: one ACP per device container (only that device and the MEC app may write).
    Both layouts: risk / alert / control / nearmiss - the MEC app writes, devices may only read."""
    from edgeguard.onem2m import CREATE, RETRIEVE, DISCOVERY, ALL_OPS
    mec = cfg["cse"]["origin"]
    orig = {d: config.device_origin(cfg, d) for d in p["device_ae"]}
    for group in (() if devices_done else ("workers", "forklifts", "cameras")):
        for dev, path in p[group].items():
            o = orig.get(dev)
            if not o:
                continue
            acp = c.with_retry(c.create_acp, p["ae"], f"acp_{dev}",
                               [([mec], ALL_OPS), ([o], CREATE | RETRIEVE)], [mec])
            c.set_acpi(path, f"{p['ae']}/acp_{dev}", acp.get("ri"))
            print(f"   ACP {path}: write = {o}, {mec}")
    readers = [o for o in orig.values()]
    for leaf in ("risk", "alert", "control", "nearmiss"):
        acp = c.with_retry(c.create_acp, p["ae"], f"acp_{leaf}",
                           [([mec], ALL_OPS)] + ([(readers, RETRIEVE | DISCOVERY)] if readers else []), [mec])
        c.set_acpi(p[leaf], f"{p['ae']}/acp_{leaf}", acp.get("ri"))
        print(f"   ACP {p[leaf]}: write = {mec}, read = devices")


if __name__ == "__main__":
    main()
