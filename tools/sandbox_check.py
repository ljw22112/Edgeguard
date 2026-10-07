"""Status of the EdgeGuard <-> ETSI MEC Sandbox connection (run while connected).

    docker compose run --rm sandbox-check        # in deploy/

Counts what flowed: MEC 013 fixes written by MEC-IPE into the CSE, IPE containers the MEC app
subscribed to, fixes the MEC app turned into tracks, RNIS cell load, alerts; writes
deploy/sandbox/report.json (copy it to results/ to keep it).
"""
import json
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard import config   # noqa: E402

MEC = os.environ.get("MEC_URL", "http://mec:9090")


def main():
    cfg = config.load()
    ms = cfg.get("mec_services") or {}
    cl = config.client(cfg)
    root = (ms.get("ipe") or {}).get("root", "MEC-IPE")
    ues = cl.discover(f"{root}/location") if ms.get("enabled") else []
    cells = cl.discover(f"{root}/rnis") if ms.get("enabled") else []
    cins = 0
    for p in ues:
        try:
            r = cl.request("GET", p)
            cins += int((r.get("m2m:cnt") or {}).get("cni") or 0)
        except Exception:
            pass
    h1 = requests.get(f"{MEC}/health", timeout=5).json()
    time.sleep(5)
    h2 = requests.get(f"{MEC}/health", timeout=5).json()
    st = requests.get(f"{MEC}/state", timeout=5).json()
    live = {k: v for k, v in st["tracks"].items() if not v.get("stale")}
    rep = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sandbox_url": (cfg.get("sandbox") or {}).get("url"), "mec_base_url": ms.get("base_url"),
        "location_source": ms.get("location_source"),
        "ipe_ue_containers": len(ues), "ipe_cell_containers": len(cells), "ipe_location_cins_kept": cins,
        "mec_ipe_subscriptions": h2["mec"]["ipe_subscriptions"],
        "mec_location_fixes": h2["mec"]["location_fixes"],
        "fixes_per_s": round((h2["mec"]["location_fixes"] - h1["mec"]["location_fixes"]) / 5, 2),
        "unknown_ue": h2["mec"]["unknown_ue"], "cell_loads": h2["mec"].get("cell_loads"),
        "network": h2["network"], "live_tracks": len(live),
        "tracks": {k: {"kind": v["kind"], "pos": v["pos"], "speed": round((v["vel"][0] ** 2 + v["vel"][1] ** 2) ** .5, 2)}
                   for k, v in sorted(live.items())},
        "pairs_assessed": len(st["pairs"]), "alerts_sent": h2["alerts_sent"],
    }
    ok = rep["ipe_ue_containers"] > 0 and rep["mec_ipe_subscriptions"] > 0 and rep["fixes_per_s"] > 0
    rep["connected"] = ok
    out = os.path.join(ROOT, "deploy", "sandbox", "report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(rep, open(out, "w"), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != "tracks"}, indent=1))
    print("CONNECTED: real MEC data is flowing through oneM2M" if ok else
          "NOT CONNECTED: see docker compose logs mec-ipe mec")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
