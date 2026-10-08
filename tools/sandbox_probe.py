"""Connect EdgeGuard to a live ETSI MEC Sandbox (https://try-mec.etsi.org).

    docker compose run --rm sandbox-setup <sandbox base URL>          # in deploy/
    python tools/sandbox_probe.py <URL> --out deploy/sandbox/overrides.yaml

1. finds the Location API (MEC 013) under the URL the Sandbox dashboard shows
   (tries <url>, <url>/location/v3, <url>/location/v2 ...),
2. reads the UEs twice, a few seconds apart: UEs faster than --vehicle-mps are vehicles
   (mapped to forklifts), the others pedestrians (workers),
3. puts the site origin at the centre of the UEs, and
4. writes a config override that enables the MEC services through MEC-IPE
   (location_source: cse) with that UE map.  `docker compose --profile sandbox up -d`
   then runs MEC-IPE against the Sandbox and restarts the MEC app with it.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.mec_services import SiteFrame, cell_load_of                    # noqa: E402

LOCATION_APIS = ("location/v3", "location/v2")
RNIS_APIS = ("rni/v2",)


def users_from(body):
    return ((body or {}).get("userList") or {}).get("user") or []


def get(session, url, **params):
    r = session.get(url, params=params or None, timeout=10)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else None)


KNOWN_SUFFIXES = ("location/v3", "location/v2", "rni/v2", "rni/v1")


def strip_api(url):
    """https://.../mep1/location/v2[/...] -> https://.../mep1"""
    url = url.rstrip("/")
    for suf in KNOWN_SUFFIXES:
        i = url.find("/" + suf)
        if i >= 0:
            return url[:i]
    return url


def find_api(session, base, apis, probes):
    """(base_url, api, body) such that base_url/api/<one of probes> answers 200."""
    given = [api for api in apis if "/" + api in base]          # the version in the URL goes first
    base = strip_api(base)
    tried = []
    for api in given + [api for api in apis if api not in given]:
        for probe in probes:
            url = f"{base}/{api}/{probe}"
            try:
                r = session.get(url, timeout=15)
                tried.append(f"{url} -> HTTP {r.status_code} {r.text[:160]!r}")
                if r.status_code == 200:
                    return base, api, (r.json() if "json" in r.headers.get("content-type", "") else None)
            except requests.RequestException as e:
                tried.append(f"{url} -> {type(e).__name__}: {str(e)[:160]}")
    raise SystemExit("No MEC API answered. Tried:\n  " + "\n  ".join(tried) +
                     "\nCheck that the network scenario is still deployed in the Sandbox dashboard.")


def all_users(session, root):
    """Every located UE: queries/users, or zone by zone when the unfiltered query is empty."""
    code, body = get(session, f"{root}/queries/users")
    users = users_from(body) if code == 200 else []
    if users:
        return users
    code, body = get(session, f"{root}/queries/zones")
    zones = ((body or {}).get("zoneList") or {}).get("zone") or [] if code == 200 else []
    out = {}
    for z in zones:
        zid = z.get("zoneId")
        if zid:
            c, b = get(session, f"{root}/queries/users", zoneId=zid)
            for u in users_from(b) if c == 200 else []:
                out[u.get("address")] = u
    return list(out.values())


def latlon(u):
    li = u.get("locationInfo") or u
    first = lambda v: v[0] if isinstance(v, list) else v                      # noqa: E731
    lat, lon = first(li.get("latitude")), first(li.get("longitude"))
    return (float(lat), float(lon)) if lat is not None and lon is not None else None


def classify_series(snaps, dt, vehicle_mps, forced=()):
    """address -> (peak speed m/s, kind) over consecutive snapshots taken dt apart.
    The peak, not one interval, decides: vehicles slow down at turns and stops."""
    peak = {}
    for s1, s2 in zip(snaps, snaps[1:]):
        k, origin = classify(s1, s2, dt, vehicle_mps)
        for addr, (v, _) in k.items():
            peak[addr] = max(peak.get(addr, 0.0), v)
    out = {a: (v, "forklift" if (v >= vehicle_mps or a in forced) else "worker") for a, v in peak.items()}
    return out, classify(snaps[0], snaps[-1], dt, vehicle_mps)[1]


def classify(snap1, snap2, dt, vehicle_mps):
    """address -> (speed m/s, kind) from two snapshots."""
    pts = [p for p in (latlon(u) for u in snap1.values()) if p]
    lat0 = sum(p[0] for p in pts) / len(pts)
    lon0 = sum(p[1] for p in pts) / len(pts)
    frame = SiteFrame(lat0, lon0)
    out = {}
    for addr, u in snap2.items():
        a, b = latlon(snap1.get(addr, {})) if addr in snap1 else None, latlon(u)
        if b is None:
            continue
        v = 0.0
        if a:
            (x0, y0), (x1, y1) = frame.to_xy(*a), frame.to_xy(*b)
            v = math.hypot(x1 - x0, y1 - y0) / dt
        out[addr] = (round(v, 2), "forklift" if v >= vehicle_mps else "worker")
    return out, (round(lat0, 6), round(lon0, 6))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="Sandbox base URL from the dashboard, e.g. https://try-mec.etsi.org/sbxXXXX/mep1")
    ap.add_argument("--out", default=os.path.join(ROOT, "deploy", "sandbox", "overrides.yaml"))
    ap.add_argument("--wait", type=float, default=12.0, help="seconds to observe the UEs (peak speed decides)")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between snapshots")
    ap.add_argument("--forklifts", default="", help="comma-separated UE addresses that are vehicles regardless of speed")
    ap.add_argument("--vehicle-mps", type=float, default=3.0, help="faster than this = vehicle (forklift)")
    ap.add_argument("--max-ues", type=int, default=40, help="map at most this many UEs")
    a = ap.parse_args()

    s = requests.Session()
    base, loc_api, _ = find_api(s, a.url, LOCATION_APIS, ("queries/users", "queries/zones"))
    root = f"{base}/{loc_api}"
    print(f"Location API: {root}")
    snap1 = {u.get("address"): u for u in all_users(s, root) if u.get("address")}
    if not snap1:
        raise SystemExit("The Location API answered but reports no UEs. Deploy a network scenario in the "
                         "Sandbox dashboard and start UE movement, then run this again.")
    snaps = [snap1]
    for _ in range(max(1, round(a.wait / a.interval))):
        time.sleep(a.interval)
        snaps.append({u.get("address"): u for u in all_users(s, root) if u.get("address")})
    snap2 = snaps[-1]
    forced = {x.strip() for x in a.forklifts.split(",") if x.strip()}
    kinds, (lat0, lon0) = classify_series(snaps, a.interval, a.vehicle_mps, forced)
    rnis_api = None
    try:
        b2, rnis_api, body = find_api(s, base, RNIS_APIS, ("queries/layer2_meas",))
        cells = [c for c in (body or {}).get("cellInfo") or [] if cell_load_of(c) is not None]
        print(f"RNIS: {b2}/{rnis_api} ({len(cells)} cells with load data)")
    except SystemExit:
        print("RNIS: not available in this scenario (congestion margin stays off)")

    ue_map, n = {}, {"worker": 0, "forklift": 0}
    for addr, (v, kind) in sorted(kinds.items(), key=lambda kv: (kv[1][1] != "forklift", kv[0]))[:a.max_ues]:
        n[kind] += 1
        ue_map[str(addr)] = {"id": f"sbx_{'veh' if kind == 'forklift' else 'ped'}{n[kind]:02d}", "kind": kind}
    frame = SiteFrame(lat0, lon0)
    print(f"\n{len(snap2)} UEs located, site origin {lat0}, {lon0}")
    print(f"{'address':24s} {'id':12s} {'kind':9s} {'speed':>7s}   x / y (m)")
    for addr, m in ue_map.items():
        p = latlon(snap2[addr])
        x, y = frame.to_xy(*p) if p else (float("nan"),) * 2
        print(f"{addr:24s} {m['id']:12s} {m['kind']:9s} {kinds[addr][0]:6.1f}   {x:8.1f} / {y:8.1f}")

    over = {
        "mec_services": {
            "enabled": True, "location_source": "cse", "base_url": base, "location_api": loc_api,
            "rnis_api": rnis_api or "rni/v2", "origin": {"lat": lat0, "lon": lon0}, "ue_map": ue_map,
            "uwb_stale_s": 0.0, "cell_id": None,
        },
        "rate_control": {"enabled": False},            # Sandbox UEs are not ours to command
        "sandbox": {"url": a.url, "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "speeds_mps": {k: kinds[k][0] for k in ue_map}},
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as fh:
        fh.write("# written by tools/sandbox_probe.py - delete this file to leave Sandbox mode\n")
        yaml.safe_dump(over, fh, sort_keys=False)
    print(f"\nwrote {a.out}: {n['worker']} pedestrians -> workers, {n['forklift']} vehicles -> forklifts")
    print("next: docker compose --profile sandbox up -d --force-recreate")


if __name__ == "__main__":
    main()
