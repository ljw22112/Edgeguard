"""Check the SDT data model on a running CSE (data_model "sdt", docs/data-model.md).

    python deploy/check_sdt.py [--config ...] [--mec http://localhost:9090] [--onboard]

Run after tools/setup_resources.py and a few seconds of device traffic (scripts/run_live_demo.sh or
tools/sdt_demo.py).  Checks:
  1. every worker tag / forklift module has its device twin (flexContainer specializations, cnd)
  2. label discovery (lbl=egs:module/kinematics) finds every kinematics module
  3. kinematics modules keep a history (flexContainerInstances, mni)
  4. semantic query (SPARQL over the SAREF descriptions) answers with the twin paths
  5. another device cannot update a twin (ACP, 403)
  6. --onboard: a device that registers itself appears in the MEC app without configuration
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from edgeguard import config, sdt                    # noqa: E402
from edgeguard.onem2m import OneM2MError, OneM2MClient  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--mec", default="http://localhost:9090")
    ap.add_argument("--onboard", action="store_true", help="also register a new device and wait for the MEC app")
    a = ap.parse_args()
    cfg = config.load(a.config)
    p = config.paths(cfg)
    c = config.client(cfg)
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok)))
        print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))

    if p.get("data_model") != "sdt":
        sys.exit("config is not data_model sdt")
    kinds = {dev: "worker" for dev in cfg["devices"].get("workers", [])}
    kinds.update({dev: "forklift" for dev in cfg["devices"].get("forklifts", [])})

    ok, bad = True, []
    for dev, kind in kinds.items():
        tp, cnd = sdt.DEVICE[kind][1], sdt.DEVICE[kind][2]
        try:
            r = c.request("GET", p["twin"][dev])[tp]
            ok &= r.get("cnd") == cnd and f"egs:id/{dev}" in (r.get("lbl") or [])
        except (OneM2MError, KeyError) as e:
            ok, bad = False, bad + [f"{dev}: {e}"]
    check("device twins (egs:wrkTg / egs:frkMe) with labels", ok, "; ".join(bad))

    found = set(c.discover_label("egs:module/kinematics", ty=28))
    want = {p["workers"].get(d) or p["forklifts"].get(d) for d in kinds}
    check("label discovery finds every kinematics module", want <= found, f"{len(found)} found")

    hist = 0
    for path in want:
        try:
            la = c.request("GET", f"{path}/la")
            hist += 1 if la and any(k.startswith("egs:") for k in la) else 0
        except OneM2MError:
            pass
    check("kinematics history (flexContainerInstances)", hist == len(want), f"{hist}/{len(want)}")

    rows = c.semantic_query(sdt.query_devices(role="forklift", actuates="DriveSpeed"))
    paths = {r.get("path") for r in rows}
    fk = {p["twin"][d] for d, k in kinds.items() if k == "forklift"}
    check("semantic query: forklifts that control the drive speed (SAREF)", fk and fk <= paths,
          f"{sorted(paths)}")

    devs = list(kinds)
    if len(devs) >= 2:
        other = config.device_client(cfg, devs[1])
        try:
            other.update_fcnt(p["workers"].get(devs[0]) or p["forklifts"][devs[0]], sdt.KIN_TP, {"posX": 99.0})
            check("another device cannot update a twin (ACP)", False, "update accepted")
        except OneM2MError as e:
            check("another device cannot update a twin (ACP)", e.status == 403, f"HTTP {e.status}")

    if a.onboard:
        dev = "worker_99"
        dc = OneM2MClient(cfg["cse"]["base_url"], cfg["cse"]["cse_rn"], "SWorker99", str(cfg["cse"].get("rvi", "3")))
        dc.delete(dev)
        dc.create_ae(dev, "Nedgeguard.worker", lbl=sdt.labels(cfg, dev, "worker")[:3])
        dc.create_fcnt(dev, "egs:wrkTg", "tag", sdt.DEVICE["worker"][2], lbl=sdt.labels(cfg, dev, "worker"))
        dc.create_fcnt(f"{dev}/tag", sdt.KIN_TP, sdt.KIN_RN, sdt.KIN_CND, {"posX": 0.0, "posY": 0.0, "smpTe": 0},
                       lbl=sdt.labels(cfg, dev, "worker", "kinematics"), mni=20)
        # let the MEC app (and the MEC-IPE) read and subscribe, nobody else
        from edgeguard.onem2m import ALL_OPS, CREATE, RETRIEVE, DISCOVERY, NOTIFY, DELETE
        acp = dc.create_acp(dev, f"acp_{dev}", [(["SWorker99"], ALL_OPS),
                                               ([cfg["cse"]["origin"]], CREATE | RETRIEVE | DISCOVERY | NOTIFY | DELETE)],
                            ["SWorker99", cfg["cse"]["origin"]])
        for path, tp in ((f"{dev}/tag", "egs:wrkTg"), (f"{dev}/tag/kinematics", sdt.KIN_TP)):
            dc.set_acpi(path, f"{dev}/acp_{dev}", acp.get("ri"), tp=tp)
        t0, seen = time.time(), False
        while time.time() - t0 < 25 and not seen:
            dc.publish(f"{dev}/tag/kinematics", {"id": dev, "kind": "worker", "x": 40.0, "y": 40.0,
                                                 "ts": int(time.time() * 1000)})
            st = json.load(urllib.request.urlopen(f"{a.mec}/state", timeout=3))
            seen = dev in st["m2m"].get("onboarded", []) and dev in st.get("tracks", {})
            time.sleep(1.0)
        check("self-registered device onboarded by discovery (no configuration)", seen,
              f"{time.time() - t0:.1f} s")
        dc.delete(dev)

    passed = sum(ok for _, ok in results)
    print(("::notice" if passed == len(results) else "::error") + " title=check_sdt::" +
          json.dumps({"passed": passed, "total": len(results)}))
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
