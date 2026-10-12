"""oneM2M MQTT binding (TS-0010) for devices: the same API as OneM2MClient, carried over MQTT with TLS.

A forklift module or tag on a lossy radio keeps one TLS connection to the site broker instead of a new
HTTP request per sample, and it needs no inbound port: requests go out on
    /oneM2M/req/<originator>/<CSE-ID>/json
responses come back on /oneM2M/resp/<originator>/<CSE-ID>/json, and notifications for an AE whose
point of access is mqtt(s):// arrive on /oneM2M/req/<CSE-ID>/<AE-ID>/json (answered on .../resp/...).

The broker authenticates every client (password) and its ACL lets a device publish requests only under
its own originator, so it cannot speak for another device (scripts/mqtt.sh).
"""
from __future__ import annotations

import itertools
import json
import ssl
import threading
import time

import paho.mqtt.client as mqtt

from .onem2m import OneM2MClient, OneM2MError

OP = {"POST": 1, "GET": 2, "PUT": 3, "DELETE": 4}
HTTP_OF_RSC = {4000: 400, 4004: 404, 4005: 405, 4008: 408, 4103: 403, 4105: 409, 4106: 400, 4108: 403,
               5000: 500, 5103: 403, 5106: 404}
_rqi = itertools.count(1)


class MqttOneM2MClient(OneM2MClient):
    def __init__(self, host, port, cse_id, cse_rn, origin, username=None, password=None, ca=None,
                 rvi="3", timeout=5.0, on_notify=None, tls=True, certfile=None, keyfile=None):
        """certfile / keyfile: a device certificate for the broker's mutual-TLS listener (scripts/device_cert.sh);
        its CN is the originator and the broker's username, so no password is needed."""
        super().__init__(f"mqtts://{host}:{port}", cse_rn, origin, rvi, timeout)
        self.cse_id = cse_id.strip("/")
        self.on_notify = on_notify
        self._pending: dict[str, tuple[threading.Event, list]] = {}
        self.m = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{origin}-{time.time_ns() % 10**8}",
                             protocol=mqtt.MQTTv311)
        if username:
            self.m.username_pw_set(username, password)
        if tls:
            self.m.tls_set(ca_certs=ca, certfile=certfile, keyfile=keyfile, cert_reqs=ssl.CERT_REQUIRED,
                           tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.m.on_message = self._on_message
        self.connected = threading.Event()
        self.connect_rc = None

        def on_connect(c, u, flags, rc, props=None):
            self.connect_rc = rc
            if not rc.is_failure:
                c.subscribe([(f"/oneM2M/resp/{self.origin}/{self.cse_id}/json", 1),
                             (f"/oneM2M/req/{self.cse_id}/{self.origin}/json", 1)])
            self.connected.set()
        self.m.on_connect = on_connect
        try:
            self.m.connect(host, port, keepalive=30)
        except (ssl.SSLError, OSError) as e:          # handshake refused (no / revoked / foreign certificate)
            raise ConnectionRefusedError(f"TLS handshake refused: {e}") from e
        self.m.loop_start()
        if not self.connected.wait(timeout) or self.connect_rc is None or self.connect_rc.is_failure:
            self.close()
            raise ConnectionRefusedError(f"MQTT connect refused: {self.connect_rc}")
        time.sleep(0.1)                                            # subscriptions in place

    def close(self):
        self.m.loop_stop()
        try:
            self.m.disconnect()
        except Exception:
            pass

    # --- MQTT plumbing ------------------------------------------------------------------------------
    def _on_message(self, c, u, msg):
        try:
            body = json.loads(msg.payload)
        except ValueError:
            return
        if msg.topic.startswith("/oneM2M/resp/"):
            ev = self._pending.get(str(body.get("rqi")))
            if ev:
                ev[1].append(body)
                ev[0].set()
        elif msg.topic.startswith("/oneM2M/req/"):                # notification from the CSE
            if self.on_notify:
                try:
                    self.on_notify(body.get("pc") or {}, time.time())
                except Exception:
                    pass
            c.publish(f"/oneM2M/resp/{self.cse_id}/{self.origin}/json", json.dumps(
                {"rsc": 2000, "rqi": body.get("rqi"), "to": body.get("fr"), "fr": self.origin, "rvi": self.rvi}), qos=1)

    def request(self, method, path, ty=None, body=None, ok_conflict=False, params=None):
        rqi = f"mq{next(_rqi)}"
        path = path.strip("/")
        prim = {"op": OP[method] if not (method == "POST" and ty is None) else 5,
                "to": self.cse_rn + (f"/{path}" if path else ""), "fr": self.origin, "rqi": rqi, "rvi": self.rvi}
        if ty is not None and method == "POST":
            prim["ty"] = ty
        if body is not None:
            prim["pc"] = body
        for k, v in (params or {}).items():
            prim.setdefault("fc" if k in ("ty", "lbl", "fu") else k, {})
            if k in ("ty", "lbl", "fu"):
                prim["fc"][k] = v
            else:
                prim[k] = v
        ev = (threading.Event(), [])
        self._pending[rqi] = ev
        try:
            self.m.publish(f"/oneM2M/req/{self.origin}/{self.cse_id}/json", json.dumps(prim), qos=1)
            if not ev[0].wait(self.timeout):
                raise OneM2MError(408, "4008", "no response over MQTT (refused by the broker ACL?)", path)
        finally:
            self._pending.pop(rqi, None)
        rsp = ev[1][0]
        rsc = int(rsp.get("rsc", 5000))
        if rsc == 4105 and ok_conflict:
            return None
        if rsc >= 4000:
            raise OneM2MError(HTTP_OF_RSC.get(rsc, 400 if rsc < 5000 else 500), str(rsc), json.dumps(rsp.get("pc"))[:300], path)
        return rsp.get("pc")
