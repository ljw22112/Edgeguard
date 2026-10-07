"""Check a demo run of the compose stack (used by CI and by hand).

    python3 deploy/check_demo.py deploy/out/devices.json http://localhost:9090/health

Passes when every played encounter was warned at least LEAD_REQ seconds before contact,
alerts reached the devices, no device write failed, and the MEC app counted the alerts.
"""
import json
import sys
import urllib.request

LEAD_REQ = 1.0


def main(path, health_url):
    d = json.load(open(path))
    health = json.load(urllib.request.urlopen(health_url, timeout=5))
    leads = d.get("first_alert_lead_s") or []
    lat = sorted(d.get("latencies_ms") or [])
    problems = []
    if len(leads) != d.get("runs"):
        problems.append(f"{len(leads)} of {d.get('runs')} encounters warned")
    if any(x < LEAD_REQ for x in leads):
        problems.append(f"lead below {LEAD_REQ} s: {leads}")
    if not d.get("alerts"):
        problems.append("no alerts reached the devices")
    if d.get("write_failures"):
        problems.append(f"{d['write_failures']} device writes failed")
    if not health.get("alerts_sent"):
        problems.append("MEC app sent no alerts")
    print(json.dumps({"runs": d.get("runs"), "leads_s": leads, "alerts": d.get("alerts"),
                      "latency_ms_p50": lat[len(lat) // 2] if lat else None,
                      "write_failures": d.get("write_failures"), "mec_alerts_sent": health.get("alerts_sent")}))
    if problems:
        print("FAIL: " + "; ".join(problems))
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
