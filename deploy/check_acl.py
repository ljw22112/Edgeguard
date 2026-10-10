"""oneM2M structure and access-control check on the running stack (used by CI and by hand).

    python3 deploy/check_acl.py [http://localhost:7579/Mobius]

Each device is its own AE; nobody may write into another device's AE or the MEC app's outputs:
  SWorker01   -> worker_01/location    201 (its own AE)
  SWorker01   -> forklift_01/motion    403 (forged forklift data)
  SWorker01   -> EdgeGuard/alert       403 (fake alert)
  SIntruder   -> worker_01/location    403 (unknown device)
and the tree is what docs/deployment.md shows (device AEs with containers, MEC AE outputs, subscriptions).
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:7579/Mobius"
_ri = [0]


def req(method, path, origin, body=None, ty=None):
    _ri[0] += 1
    h = {"X-M2M-Origin": origin, "X-M2M-RI": f"acl{_ri[0]}", "X-M2M-RVI": "2a", "Accept": "application/json"}
    if body is not None:
        h["Content-Type"] = f"application/json;ty={ty}"
    r = urllib.request.Request(f"{BASE}/{path}" if path else BASE, method=method, headers=h,
                               data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def main():
    cin = lambda who: {"m2m:cin": {"con": {"id": who, "kind": "acl_test", "ts": 0}}}  # noqa: E731
    checks = [
        ("device AE worker_01 exists", req("GET", "worker_01", "SWorker01")[0] == 200),
        ("device AE forklift_01 exists", req("GET", "forklift_01", "SForklift01")[0] == 200),
        ("MEC AE EdgeGuard exists", req("GET", "EdgeGuard", "SEdgeGuard")[0] == 200),
        ("MEC subscribed to worker_01/location",
         req("GET", "worker_01/location/sub_mec", "SEdgeGuard")[0] == 200),
        ("SWorker01 writes its own location", req("POST", "worker_01/location", "SWorker01", cin("worker_01"), 4)[0] == 201),
        ("SWorker01 cannot forge forklift data",
         req("POST", "forklift_01/motion", "SWorker01", cin("forklift_01"), 4)[0] in (403, 401)),
        ("SWorker01 cannot write a fake alert",
         req("POST", "EdgeGuard/alert", "SWorker01", {"m2m:cin": {"con": {"event": "clear"}}}, 4)[0] in (403, 401)),
        ("unknown originator is refused", req("POST", "worker_01/location", "SIntruder", cin("x"), 4)[0] in (403, 401)),
    ]
    ok = all(v for _, v in checks)
    for name, v in checks:
        print(("PASS " if v else "FAIL ") + name)
    summary = json.dumps({"passed": sum(v for _, v in checks), "total": len(checks)})
    print(("::notice" if ok else "::error") + " title=check_acl::" + summary)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
