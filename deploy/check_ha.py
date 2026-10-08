"""Fail-over check for the compose `ha` profile (used by CI and by hand).

    MEC_HA=1 docker compose --profile ha up -d
    python3 deploy/check_ha.py

Finds the leader through /health of mec (9090) and mec2 (9092), stops the leader container,
and measures (1) how long until the standby reports itself leader and (2) the longest gap
between control heartbeats in the CSE across the fail-over (<ae>/control/la, `ts` field written
by whichever instance leads).  Passes when the heartbeat gap stays below the 2 s after which a
forklift falls back to its local rule (edgeguard/device_policy.py LOCAL_AFTER_S).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HEALTH = {"mec": "http://localhost:9090/health", "mec2": "http://localhost:9092/health"}
CSE = os.environ.get("CSE_URL", "http://localhost:7579/Mobius/EdgeGuard/control/la")
GAP_LIMIT_S = 2.0


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    return json.load(urllib.request.urlopen(req, timeout=2))


def leader_of(name):
    try:
        ha = get(HEALTH[name]).get("ha") or {}
        return bool(ha.get("leader"))
    except Exception:
        return None


def heartbeat_ts():
    try:
        r = get(CSE, {"X-M2M-Origin": "SEdgeGuard", "X-M2M-RI": "ha-check", "X-M2M-RVI": "2a",
                      "Accept": "application/json"})
        con = r["m2m:cin"]["con"]
        con = json.loads(con) if isinstance(con, str) else con
        return con.get("ts")
    except Exception:
        return None


def fail(msg):
    print("::error title=check_ha::" + msg)                 # readable via the CI annotations API
    sys.exit(msg)


def main():
    deadline = time.time() + 120
    while time.time() < deadline:                      # both up, exactly one leader
        a, b = leader_of("mec"), leader_of("mec2")
        if a is not None and b is not None and a != b and heartbeat_ts():
            break
        time.sleep(0.5)
    else:
        fail(f"no single leader within 120 s (mec={leader_of('mec')}, mec2={leader_of('mec2')})")
    leader, standby = ("mec", "mec2") if leader_of("mec") else ("mec2", "mec")
    print(f"leader {leader}, standby {standby}")

    seen, last = [], None
    t_end = time.time() + 3
    while time.time() < t_end:                         # heartbeats before the failure
        ts = heartbeat_ts()
        if ts and ts != last:
            seen.append(ts)
            last = ts
        time.sleep(0.05)
    t_kill = time.time()
    subprocess.run(["docker", "compose", "kill", leader], check=True)
    t_lead = None
    t_end = time.time() + 15
    while time.time() < t_end:
        ts = heartbeat_ts()
        if ts and ts != last:
            seen.append(ts)
            last = ts
        if t_lead is None and leader_of(standby):
            t_lead = time.time() - t_kill
        if t_lead is not None and time.time() - t_kill > t_lead + 4:
            break
        time.sleep(0.05)
    gaps = [(b - a) / 1000 for a, b in zip(seen, seen[1:])]
    worst = max(gaps) if gaps else None
    out = {"takeover_s": None if t_lead is None else round(t_lead, 2),
           "max_heartbeat_gap_s": None if worst is None else round(worst, 2),
           "heartbeats": len(seen), "limit_s": GAP_LIMIT_S}
    print(json.dumps(out))
    print("::notice title=check_ha::" + json.dumps(out))   # result readable via the annotations API
    if t_lead is None:
        fail("standby never took over")
    if worst is None or worst >= GAP_LIMIT_S:
        fail(f"heartbeat gap {worst} s >= {GAP_LIMIT_S} s")
    print("PASS")


if __name__ == "__main__":
    main()
