"""oneM2M MQTT binding request primitives (edgeguard/mqtt_binding.py) against a fake broker client."""
import json
import threading

import pytest

from edgeguard import mqtt_binding
from edgeguard.onem2m import OneM2MError


class FakeRC:
    is_failure = False


class FakePaho:
    """Answers every request published on /oneM2M/req/<orig>/<cse>/json with the scripted response."""
    def __init__(self, *a, **kw):
        self.published, self.subs, self.reply = [], [], {"rsc": 2001, "pc": {"ok": 1}}

    def username_pw_set(self, u, p): self.user = u
    def tls_set(self, **kw): self.tls = kw
    def connect(self, host, port, keepalive=30): self.on_connect(self, None, {}, FakeRC())
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): pass
    def subscribe(self, topics): self.subs += [t for t, _ in topics]

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, json.loads(payload)))
        if topic.startswith("/oneM2M/req/") and self.reply is not None:
            prim = json.loads(payload)
            msg = type("M", (), {"topic": "/oneM2M/resp/x/y/json",
                                 "payload": json.dumps({**self.reply, "rqi": prim["rqi"]}).encode()})
            threading.Timer(0.01, self.on_message, (self, None, msg)).start()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(mqtt_binding.mqtt, "Client", FakePaho)
    monkeypatch.setattr(mqtt_binding.time, "sleep", lambda s: None)
    return mqtt_binding.MqttOneM2MClient("h", 8883, "/id-sec", "cse-sec", "Cfk", "Cfk", "pw", ca="ca.crt", timeout=1)


def test_subscribes_to_its_responses_and_notifications(client):
    assert client.m.subs == ["/oneM2M/resp/Cfk/id-sec/json", "/oneM2M/req/id-sec/Cfk/json"]
    assert client.m.tls["ca_certs"] == "ca.crt"


def test_create_is_a_request_primitive_on_its_own_topic(client):
    assert client.create_cin("fk/motion", {"x": 1}) == {"ok": 1}
    topic, prim = client.m.published[-1]
    assert topic == "/oneM2M/req/Cfk/id-sec/json"
    assert prim["op"] == 1 and prim["ty"] == 4 and prim["to"] == "cse-sec/fk/motion" and prim["fr"] == "Cfk"
    assert prim["pc"] == {"m2m:cin": {"con": {"x": 1}}}


def test_error_codes_map_to_http_like_errors(client):
    client.m.reply = {"rsc": 4103}
    with pytest.raises(OneM2MError) as e:
        client.request("GET", "fk/motion")
    assert e.value.status == 403
    client.m.reply = {"rsc": 4105}
    assert client.create_container("fk", "motion") is None        # ok_conflict


def test_no_response_is_a_timeout(client):
    client.m.reply = None
    client.timeout = 0.05
    with pytest.raises(OneM2MError) as e:
        client.request("GET", "fk")
    assert e.value.status == 408


def test_notification_is_delivered_and_answered(client):
    got = []
    client.on_notify = lambda pc, t: got.append(pc)
    msg = type("M", (), {"topic": "/oneM2M/req/id-sec/Cfk/json",
                         "payload": json.dumps({"op": 5, "fr": "/id-sec", "rqi": "n1", "pc": {"m2m:sgn": {}}}).encode()})
    client._on_message(client.m, None, msg)
    assert got == [{"m2m:sgn": {}}]
    topic, rsp = client.m.published[-1]
    assert topic == "/oneM2M/resp/id-sec/Cfk/json" and rsp["rsc"] == 2000 and rsp["rqi"] == "n1"
