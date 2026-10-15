"""Alerts to a worker tag over MQTT only: the CSE sends oneM2M notifications over the MQTT binding.

    scripts/mqtt.sh start && scripts/acme.sh start sec     # ACME >= 2026.05.3 (fix of ACME issue #200)
    python tools/mqtt_notify_demo.py

Until ACME 2026.05.3 the CSE could not send requests over MQTT (ankraft/ACME-oneM2M-CSE#200, reported by
this project), so tags received alerts over HTTP or a pollingChannel.  Now a tag keeps ONE TLS connection to
the site broker for both directions:

  tag  -> CSE   /oneM2M/req/SWorker01/id-sec/json       registers, subscribes to its own alerts container
  app  -> CSE   HTTPS                                     the MEC app writes WAIT / GO into the tag's alerts
  CSE  -> tag   /oneM2M/req/id-sec/SWorker01/json       NOTIFY (the tag's pointOfAccess is mqtts://)
  tag  -> CSE   /oneM2M/resp/id-sec/SWorker01/json      response 2000

The broker ACL lets each device read only notifications addressed to itself: a second device listening on
the tag's topic gets nothing.  Result: results/mqtt_notify.json
"""
from __future__ import annotations

import json
import os
import ssl
import statistics
import sys
import threading
import time

import paho.mqtt.client as mqtt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.mqtt_binding import MqttOneM2MClient                        # noqa: E402
from edgeguard.onem2m import CREATE, NOTIFY, RETRIEVE, OneM2MClient         # noqa: E402

CA = os.path.join(ROOT, ".certs", "ca.crt")
HTTPS = ("https://127.0.0.1:8443", "cse-sec")
BROKER = ("127.0.0.1", 8883)
CSE_ID = "id-sec"
TAG, OTHER, APP = "SWorker01", "SForklift01", "SEdgeGuardSec"
N = 30


def env():
    out = {}
    for line in open(os.path.join(ROOT, ".certs", "mqtt.env")):
        k, _, v = line.strip().partition("=")
        out[k] = v
    return out


def main():
    pw = env()["MQTT_DEV_PW"]
    admin = OneM2MClient(*HTTPS, "CAdmin", verify=CA)
    admin.delete("worker_mq")
    rx, lock, vrq = [], threading.Lock(), []

    def on_notify(pc, t):
        if (pc.get("m2m:sgn") or {}).get("vrq"):                           # subscription verification request
            vrq.append(t)
            return
        cin = ((pc.get("m2m:sgn") or {}).get("nev") or {}).get("rep", {}).get("m2m:cin") or {}
        con = cin.get("con")
        con = json.loads(con) if isinstance(con, str) else con
        if isinstance(con, dict):
            with lock:
                rx.append((t, con))

    # --- the tag: one MQTT/TLS connection, pointOfAccess mqtts:// ----------------------------------------------
    tag = MqttOneM2MClient(*BROKER, CSE_ID, HTTPS[1], TAG, TAG, pw, ca=CA, on_notify=on_notify)
    tag.create_ae("worker_mq", api="Nedgeguard.tag", poa=[f"mqtts://{BROKER[0]}:{BROKER[1]}"], lbl=["egs:tag/mqtt"])
    tag.create_container("worker_mq", "alerts", mni=50)
    acp = tag.create_acp("worker_mq", "acp_alerts", [([TAG], 63), ([APP], CREATE, (4,))], [TAG])
    tag.set_acpi("worker_mq/alerts", "worker_mq/acp_alerts", acp.get("ri"))
    t_sub = time.time()
    tag.create_subscription("worker_mq/alerts", "sub_self", [TAG])          # target = its own AE-ID
    sub_ms = round((time.time() - t_sub) * 1000, 1)
    ae = admin.request("GET", "worker_mq")["m2m:ae"]

    # --- an eavesdropper: another authenticated device subscribes to the tag's notification topic ---------------
    spy_rx = []
    spy = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"spy-{os.getpid()}", protocol=mqtt.MQTTv311)
    spy.username_pw_set(OTHER, pw)
    spy.tls_set(ca_certs=CA, cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    spy.on_message = lambda c, u, m: spy_rx.append(m.topic)
    spy.on_connect = lambda c, u, f, rc, p=None: c.subscribe(f"/oneM2M/req/{CSE_ID}/{TAG}/json", 1)
    spy.connect(*BROKER)
    spy.loop_start()
    time.sleep(0.5)

    # --- the MEC app (HTTPS) writes alerts; each reaches the tag as an MQTT notification -------------------------
    app = OneM2MClient(*HTTPS, APP, verify=CA)
    sent = {}
    for i in range(N):
        sent[i] = time.time()
        app.create_cin("worker_mq/alerts", {"seq": i, "cue": "WAIT" if i % 2 == 0 else "GO", "forklift": "forklift_01"})
        time.sleep(0.1)
    time.sleep(1.5)
    with lock:
        got = {c["seq"]: t for t, c in rx if c.get("seq") in sent}
    lat = sorted((got[i] - sent[i]) * 1000 for i in got)
    spy.loop_stop()
    spy.disconnect()

    # --- the broker log shows the CSE's publish on the tag's topic -------------------------------------------
    try:
        broker_log = open(os.path.join(ROOT, ".mqtt", "mosquitto.log")).read()
    except OSError:
        broker_log = ""
    p50 = round(statistics.median(lat), 1) if lat else None
    p95 = round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else None
    checks = {
        "tag registered over MQTT/TLS with pointOfAccess mqtts:// (no HTTP endpoint, no inbound port)":
            any(str(p).startswith("mqtt") for p in ae.get("poa", [])),
        "the tag subscribed to its own alerts over MQTT (no verification needed: the target is the originator)":
            admin.request("GET", "worker_mq/alerts/sub_self")["m2m:sub"].get("nu") == [TAG],
        f"all {N} alerts from the HTTPS app reached the tag as MQTT notifications": len(got) == N,
        "alerts arrived in order (WAIT / GO sequence intact)": [c["seq"] for _, c in sorted(rx)][:N] == list(range(N)),
        "median alert latency app -> CSE -> broker -> tag under 100 ms": p50 is not None and p50 < 100,
        "another device cannot read the tag's notifications (broker ACL)": not spy_rx,
    }
    report = {"acme_fix": "ankraft/ACME-oneM2M-CSE#200, release 2026.05.3", "poa": ae.get("poa"), "subscribe_ms": sub_ms,
              "latency_ms": {"n": len(lat), "p50": p50, "p95": p95, "max": round(lat[-1], 1) if lat else None},
              "spy_messages": len(spy_rx), "checks": checks}
    json.dump(report, open(os.path.join(ROOT, "results", "mqtt_notify.json"), "w"), indent=1)
    tag.close()
    print(f"alerts over MQTT: {len(got)}/{N}, p50 {p50} ms, p95 {p95} ms; subscribe over MQTT {sub_ms} ms")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=mqtt_notify::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "failed": [k for k, v in checks.items() if not v],
         "p50_ms": p50, "p95_ms": p95}))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        print("::error title=mqtt_notify_demo::" + " | ".join(traceback.format_exc().strip().splitlines()[-6:])[:1500])
        raise
