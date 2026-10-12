"""Device identity by certificate: mutual TLS on the MQTT broker, per-device certificates, rotation, revocation.

    scripts/mqtt.sh start && ACME_MQTT=1 scripts/acme.sh start in
    python tools/device_identity_demo.py

Each device gets its own key and certificate from the site CA (scripts/device_cert.sh); the CN is its
oneM2M originator.  On the broker's mutual-TLS listener (:8884) the certificate is the device's identity:
no password on the device, and the per-originator ACL applies to the CN.  Checked: a device registers and
publishes with its certificate only; no certificate, a certificate from another CA, and speaking under
another device's originator are refused; after rotation (new key, old serial revoked, CRL reloaded) the old
certificate is refused and the new one works.  Result: results/device_identity.json
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from edgeguard.mqtt_binding import MqttOneM2MClient   # noqa: E402
from edgeguard.onem2m import OneM2MClient, OneM2MError   # noqa: E402

C = os.path.join(ROOT, ".certs")
CA = os.path.join(C, "ca.crt")
BROKER = ("127.0.0.1", 8884)
CSE_ID, CSE_RN = "id-in", "cse-in"
TAG, FK = "CmtlsTag1", "CmtlsFk1"


def sh(*args):
    return subprocess.run(["bash", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def dev(origin, cert=None, key=None, timeout=3.0):
    cert = cert or os.path.join(C, "devices", f"{origin}.crt")
    key = key or os.path.join(C, "devices", f"{origin}.key")
    return MqttOneM2MClient(*BROKER, CSE_ID, CSE_RN, origin, None, None, ca=CA, certfile=cert, keyfile=key, timeout=timeout)


def refused(fn):
    try:
        c = fn()
    except (ConnectionRefusedError, OSError) as e:
        return f"refused ({str(e)[:60]})"
    try:
        c.create_ae("probe_should_fail")
        return "accepted"
    except OneM2MError as e:
        return f"no service ({e.rsc})"
    finally:
        c.close()


def main():
    admin = OneM2MClient("http://127.0.0.1:8080", CSE_RN, "CAdmin")
    for rn in ("mtls_tag", "mtls_fk"):
        admin.delete(rn)
    for o in (TAG, FK):
        sh("scripts/device_cert.sh", "issue", o, "30")
    sh("scripts/mqtt.sh", "reload")
    time.sleep(0.5)

    # 1. a device with only its certificate
    tag = dev(TAG)
    lat = []
    tag.create_ae("mtls_tag", api="Nedgeguard.worker")
    tag.create_container("mtls_tag", "location", mni=20)
    for i in range(20):
        t0 = time.time()
        tag.create_cin("mtls_tag/location", {"seq": i, "x": i * 0.3, "y": 1.0})
        lat.append((time.time() - t0) * 1000)
    cni = admin.request("GET", "mtls_tag/location")["m2m:cnt"]["cni"]
    tag.close()

    # 2. what must fail
    def no_cert():
        return MqttOneM2MClient(*BROKER, CSE_ID, CSE_RN, TAG, None, None, ca=CA, timeout=3.0)
    tmp = tempfile.mkdtemp(prefix="rogue")
    rk, rc = os.path.join(tmp, "r.key"), os.path.join(tmp, "r.crt")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", f"/CN={TAG}",
                    "-keyout", rk, "-out", rc], capture_output=True, check=True)
    r_nocert = refused(no_cert)
    r_rogue = refused(lambda: dev(TAG, rc, rk))
    imp = "accepted"
    try:                                       # the tag's certificate, the forklift's originator
        evil = MqttOneM2MClient(*BROKER, CSE_ID, CSE_RN, FK, None, None, ca=CA,
                                certfile=os.path.join(C, "devices", f"{TAG}.crt"),
                                keyfile=os.path.join(C, "devices", f"{TAG}.key"), timeout=2.0)
        try:
            evil.create_ae("mtls_fk")
        except OneM2MError as e:
            imp = f"no response ({e.rsc})" if e.status == 408 else f"rejected {e.status}"
        evil.close()
    except ConnectionRefusedError as e:
        imp = f"refused ({e})"

    # 3. rotation: new key + certificate, old serial revoked, CRL reloaded
    sh("scripts/device_cert.sh", "issue", TAG, "30")            # keeps the old one as <TAG>.prev.crt
    old_crt, old_key = (os.path.join(C, "devices", f"{TAG}.prev.{x}") for x in ("crt", "key"))
    sh("scripts/device_cert.sh", "revoke", TAG, old_crt)
    sh("scripts/mqtt.sh", "reload")
    time.sleep(0.7)
    r_old = refused(lambda: dev(TAG, old_crt, old_key))
    try:
        t2 = dev(TAG)
        t2.create_cin("mtls_tag/location", {"seq": 99, "rotated": True})
        new_ok = True
        t2.close()
    except Exception:
        new_ok = False

    lat.sort()
    p50 = round(statistics.median(lat), 1)
    checks = {
        "device registered and published 20 samples with its certificate only (no password)": cni == 20,
        "no client certificate: refused by the broker": r_nocert.startswith("refused"),
        "certificate from another CA (same CN): refused": r_rogue.startswith("refused"),
        "a device's certificate cannot speak under another originator (ACL on the CN)": imp != "accepted"
            and "rejected" not in imp,
        "rotation: the revoked old certificate is refused": r_old.startswith("refused"),
        "rotation: the new certificate works": new_ok,
        "create over mutual TLS: median under 100 ms": p50 < 100,
    }
    report = {"create_ms": {"p50": p50, "p95": round(lat[int(0.95 * (len(lat) - 1))], 1)},
              "refusals": {"no_cert": r_nocert, "foreign_ca": r_rogue, "impersonation": imp, "revoked": r_old},
              "checks": checks}
    json.dump(report, open(os.path.join(ROOT, "results", "device_identity.json"), "w"), indent=1)
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    ok = all(checks.values())
    print(("::notice" if ok else "::error") + " title=device_identity::" + json.dumps(
        {"passed": sum(map(bool, checks.values())), "total": len(checks), "failed": [k for k, v in checks.items() if not v],
         "p50_ms": p50, "refusals": report["refusals"]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
