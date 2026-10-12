"""Secured transport: devices on the oneM2M MQTT binding over TLS, applications on HTTPS, on an ACME CSE.

    scripts/mqtt.sh start && scripts/acme.sh start sec
    python tools/secure_transport_demo.py

A forklift module registers and publishes 10 Hz motion samples over MQTT/TLS (one connection, no inbound
port); the MEC app talks to the CSE over HTTPS only and receives the samples as oneM2M notifications on
its own HTTPS endpoint (server certificate from the same site CA).  Then the
attacks that must fail: plaintext HTTP and MQTT, an untrusted certificate, a wrong broker password, a
device speaking under another device's originator (broker ACL), another device reading the forklift's
data (oneM2M ACP).  Result: results/secure_transport.json
"""
from __future__ import annotations

import json
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import statistics
import sys
import time

import paho.mqtt.client as mqtt
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.mqtt_binding import MqttOneM2MClient                 # noqa: E402
from edgeguard.onem2m import CREATE, NOTIFY, RETRIEVE, OneM2MClient, OneM2MError   # noqa: E402

CA = os.path.join(ROOT, ".certs", "ca.crt")
HTTPS = ("https://127.0.0.1:8443", "cse-sec")
BROKER = ("127.0.0.1", 8883)
CSE_ID = "id-sec"
FK, APP, WK = "Cforklift01", "SEdgeGuardSec", "Cworker01"
N = 50
NOTIFY_PORT = 9443


def env():
    out = {}
    for line in open(os.path.join(ROOT, ".certs", "mqtt.env")):
        k, _, v = line.strip().partition("=")
        out[k] = v
    return out


def mq(origin, user=None, pw=None, **kw):
    return MqttOneM2MClient(*BROKER, CSE_ID, HTTPS[1], origin, user or origin, pw, ca=CA, **kw)


def main():
    pw = env()["MQTT_DEV_PW"]
    admin = OneM2MClient(*HTTPS, "CAdmin", verify=CA)
    for rn in ("forklift_01", "EdgeGuardSec", "worker_01"):
        admin.delete(rn)

    # --- device and application on MQTT/TLS ---------------------------------------------------------
    rx = []
    fk = mq(FK, pw=pw)
    fk.create_ae("forklift_01", api="Nedgeguard.forklift")
    fk.create_container("forklift_01", "motion", mni=100)
    acp = fk.create_acp("forklift_01", "acp_forklift_01",
                        [([FK], 63), ([APP], RETRIEVE | NOTIFY | CREATE, (23,))], [FK])
    fk.set_acpi("forklift_01/motion", "forklift_01/acp_forklift_01", acp.get("ri"))
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            t = time.time()
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            self.send_response(200)
            self.send_header("X-M2M-RSC", "2000")
            self.end_headers()
            rx.append((body, t))

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", NOTIFY_PORT), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(os.path.join(ROOT, ".certs", "server.crt"), os.path.join(ROOT, ".certs", "server.key"))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    app = OneM2MClient(*HTTPS, APP, verify=CA)
    app.create_ae("EdgeGuardSec", api="Nedgeguard.mec", poa=[f"https://127.0.0.1:{NOTIFY_PORT}/notify"])
    app.create_subscription("forklift_01/motion", "sub_mec", [APP])
    time.sleep(0.3)
    rx.clear()
    sent = {}
    for i in range(N):
        sent[i] = time.time()
        fk.create_cin("forklift_01/motion", {"id": "forklift_01", "seq": i, "x": i * 0.2, "y": 3.0, "speed": 2.0})
        time.sleep(0.1)
    time.sleep(1.0)
    lat = []
    for pc, t in rx:
        cin = ((pc.get("m2m:sgn") or {}).get("nev") or {}).get("rep", {}).get("m2m:cin") or {}
        con = cin.get("con")
        con = json.loads(con) if isinstance(con, str) else con
        if isinstance(con, dict) and con.get("seq") in sent:
            lat.append((t - sent[con["seq"]]) * 1000)
    lat.sort()
    p50 = round(statistics.median(lat), 1) if lat else None
    p95 = round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else None

    # --- the application reads over HTTPS -------------------------------------------------------------
    t0 = time.time()
    la = app.latest("forklift_01/motion")
    https_ms = round((time.time() - t0) * 1000, 1)
    cni = admin.request("GET", "forklift_01/motion")["m2m:cnt"]["cni"]

    # --- what must fail ---------------------------------------------------------------------------------
    def fails(fn, *exc):
        try:
            fn()
            return False
        except exc:
            return True
    plain_http = fails(lambda: requests.get("http://127.0.0.1:8443/cse-sec", timeout=3,
                       headers={"X-M2M-Origin": "CAdmin", "X-M2M-RI": "1", "X-M2M-RVI": "3"}).raise_for_status(),
                       requests.RequestException)
    untrusted = fails(lambda: OneM2MClient(*HTTPS, APP, verify=True).request("GET", ""), requests.exceptions.SSLError)

    def raw_connect(tls, user, password):
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"probe{time.time_ns() % 10**6}")
        if user:
            c.username_pw_set(user, password)
        if tls:
            c.tls_set(ca_certs=CA, cert_reqs=ssl.CERT_REQUIRED)
        res = {}
        c.on_connect = lambda cl, u, f, rc, p=None: res.setdefault("rc", rc)
        try:
            c.connect(*BROKER, keepalive=5)
            c.loop_start()
            time.sleep(1.0)
            c.loop_stop()
            c.disconnect()
        except Exception as e:
            return f"refused ({type(e).__name__})"
        rc = res.get("rc")
        return "accepted" if rc is not None and not rc.is_failure else f"refused ({rc})"
    plain_mqtt = raw_connect(False, FK, pw)
    wrong_pw = raw_connect(True, FK, "not-the-password")
    impersonate = "accepted"
    try:
        evil = mq(WK, user=FK, pw=pw, timeout=2.0)      # forklift credentials, worker originator
        try:
            evil.create_ae("worker_01")
        except OneM2MError as e:
            impersonate = f"no response ({e.rsc})" if e.status == 408 else f"rejected {e.status}"
        evil.close()
    except ConnectionRefusedError as e:
        impersonate = f"refused ({e})"
    wk = mq(WK, pw=pw)
    wk.create_ae("worker_01", api="Nedgeguard.worker")
    acp_block = fails(lambda: wk.latest("forklift_01/motion"), OneM2MError)
    wk.close()
    fk.close()
    srv.shutdown()

    checks = {
        f"forklift registered and published {N} samples over MQTT/TLS": cni == N,
        f"MEC app received all {N} as oneM2M notifications on its HTTPS endpoint": len(lat) == N,
        "median device -> CSE -> app delivery under 100 ms": p50 is not None and p50 < 100,
        "application reads over HTTPS, server verified against the site CA": la.get("seq") == N - 1,
        "plaintext HTTP to the CSE port fails": plain_http,
        "a certificate not from the site CA is rejected by the client": untrusted,
        "plaintext MQTT to the broker is refused": plain_mqtt.startswith("refused"),
        "a wrong broker password is refused": wrong_pw.startswith("refused"),
        "a device cannot send requests under another device's originator (broker ACL)": impersonate != "accepted"
            and "rejected" not in impersonate,
        "another authenticated device cannot read the forklift's data (oneM2M ACP)": acp_block,
    }
    report = {"samples": N, "device_mqtt_to_app_https_ms": {"n": len(lat), "p50": p50, "p95": p95, "max": round(lat[-1], 1) if lat else None},
              "https_retrieve_ms": https_ms,
              "attacks": {"plain_http": plain_http, "untrusted_cert": untrusted, "plain_mqtt": plain_mqtt,
                          "wrong_password": wrong_pw, "impersonation": impersonate, "acp": acp_block},
              "checks": checks}
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(report, open(os.path.join(ROOT, "results", "secure_transport.json"), "w"), indent=1)
    print(f"device (MQTT/TLS) -> app (HTTPS notification): p50 {p50} ms, p95 {p95} ms (n={len(lat)}); HTTPS retrieve {https_ms} ms")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=secure_transport::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "failed": [k for k, v in checks.items() if not v], "p50_ms": p50, "attacks": report["attacks"]}))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
