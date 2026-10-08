"""Check the compose `monitoring` profile (used by CI and by hand).

    docker compose --profile monitoring up -d && python3 deploy/check_monitoring.py

Passes when Prometheus has scraped edgeguard_* series from a MEC app, its alert rules loaded,
and Grafana serves the provisioned EdgeGuard dashboard.
"""
import json
import sys
import time
import urllib.parse
import urllib.request

PROM = "http://localhost:9095"
GRAFANA = "http://localhost:3000"


def get(url):
    return json.load(urllib.request.urlopen(url, timeout=3))


def fail(msg):
    print("::error title=check_monitoring::" + msg)
    sys.exit(msg)


def main():
    deadline = time.time() + 90
    series = rules = dash = None
    while time.time() < deadline:
        try:
            q = urllib.parse.quote("edgeguard_samples_total")
            series = get(f"{PROM}/api/v1/query?query={q}")["data"]["result"]
            rules = [r["name"] for g in get(f"{PROM}/api/v1/rules")["data"]["groups"] for r in g["rules"]]
            dash = get(f"{GRAFANA}/api/dashboards/uid/edgeguard")["dashboard"]
            if series and rules and dash:
                break
        except Exception as e:
            print("waiting:", e)
        time.sleep(2)
    summary = json.dumps({"series": [s["metric"].get("instance_id") for s in series or []],
                      "rules": rules, "dashboard_panels": len((dash or {}).get("panels", []))})
    print(summary)
    print("::notice title=check_monitoring::" + summary)
    if not series:
        fail("Prometheus has no edgeguard_samples_total")
    if not rules:
        fail("alert rules not loaded")
    if not dash:
        fail("Grafana dashboard 'edgeguard' not provisioned")
    print("PASS")


if __name__ == "__main__":
    main()
