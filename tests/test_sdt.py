"""SDT data model (edgeguard/sdt.py): conversions, paths, notifications, the .fcp definitions."""
import json
import os
import re

from edgeguard import config, sdt
from edgeguard.onem2m import parse_notification

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg(model):
    cfg = config.load(os.path.join(ROOT, "config", "site.yaml"))
    cfg["onem2m"] = {"data_model": model}
    return cfg


def test_kinematics_round_trip():
    s = {"id": "forklift_01", "kind": "forklift", "x": 1.5, "y": -2.0, "speed": -1.2, "heading": 0.3,
         "yaw_rate": 0.05, "ts": 1700000000123, "pos_sigma": 0.1, "source": "uwb"}
    attrs = sdt.to_kin(s)
    assert attrs["posX"] == 1.5 and attrs["smpTe"] == 1700000000123 and attrs["speed"] == -1.2
    back = sdt.from_kin(attrs, lbl=sdt.labels(_cfg("sdt"), "forklift_01", "forklift", "kinematics"))
    assert back == s


def test_paths_follow_the_data_model():
    p = config.paths(_cfg("sdt"))
    assert p["data_model"] == "sdt"
    assert p["workers"]["worker_01"] == "worker_01/tag/kinematics"
    assert p["forklifts"]["forklift_01"] == "forklift_01/module/kinematics"
    assert p["twin"]["worker_01"] == "worker_01/tag"
    assert p["cameras"]["camera_01"] == "camera_01/detect"          # cameras keep contentInstances
    p = config.paths(_cfg("cin"))
    assert p["workers"]["worker_01"] == "worker_01/location" and p["twin"] == {}


def test_fcnt_notification_is_parsed():
    rep = {"egs:kinSt": {"rn": "kinematics", "cnd": sdt.KIN_CND, "posX": 2.0, "posY": 3.0, "smpTe": 5,
                         "lbl": ["egs:id/worker_01", "egs:role/worker", "egs:module/kinematics"]}}
    kind, p = parse_notification({"m2m:sgn": {"nev": {"rep": rep, "net": 1}, "sur": "x"}})
    assert kind == "fcnt" and p["tp"] == "egs:kinSt"
    s = sdt.from_kin(p)
    assert s["id"] == "worker_01" and s["kind"] == "worker" and (s["x"], s["y"], s["ts"]) == (2.0, 3.0, 5)


def test_saref_description_and_query():
    ttl = sdt.saref_turtle("forklift_01", "forklift", "forklift_01/module", zone="A")
    assert "saref:Actuator" in ttl and 'egs:resource "forklift_01/module"' in ttl and "egs:DriveSpeed" in ttl
    q = sdt.query_devices(role="forklift", zone="A", actuates="DriveSpeed")
    assert "SELECT ?d ?path ?role" in q and 'egs:zone "A"' in q


def test_fcp_defines_every_type_the_code_uses():
    text = open(os.path.join(ROOT, "config", "onem2m", "edgeguard.fcp")).read()
    defs = json.loads(re.sub(r"//[^\n]*", "", text))
    types = {d["type"]: d for d in defs}
    for kind, (_, tp, cnd, _, atp, acnd) in sdt.DEVICE.items():
        assert types[tp]["cnd"] == cnd and types[atp]["cnd"] == acnd
        assert sdt.KIN_TP in types[tp]["children"] and sdt.BAT_TP in types[tp]["children"]
    kin = {a["sname"] for a in types[sdt.KIN_TP]["attributes"]}
    assert set(sdt.to_kin({"x": 0, "y": 0, "pos_sigma": 0, "source": "u", "speed": 0, "heading": 0,
                           "yaw_rate": 0, "ts": 0})) <= kin


def test_speed_limit_module_carries_stop_points_and_plans():
    text = open(os.path.join(ROOT, "config", "onem2m", "edgeguard.fcp")).read()
    defs = {d["type"]: d for d in json.loads(re.sub(r"//[^\n]*", "", text))}
    names = {a["sname"] for a in defs["egs:spdLt"]["attributes"]}
    assert {"limit", "stpX", "stpY", "stpSo", "plans", "aebAc", "rptTe"} <= names
    rep = sdt.speed_limit_report([("w1", 1.2, True), ("w2", None, False)], stop=(3.0, -1.0, "w1"), aeb=False, ts=5)
    assert rep["limit"] == 1.2 and rep["stpX"] == 3.0 and rep["stpSo"] == "w1"
    assert sdt.plans_from_report(rep) == [["w1", 1.2, 1], ["w2", -1.0, 0]]
    alert = {"event": "refresh", "forklift": "f1", "worker": "w1",
             "actions": {"f1": {"speed_limit": 0.9, "stop_at": [4.0, 2.0]}}}
    assert sdt.speed_limit_from_alert(alert) == {"limit": 0.9, "stpX": 4.0, "stpY": 2.0, "stpSo": "w1"}
    assert "egs:StopPoint" in sdt.saref_turtle("f1", "forklift", "f1/module")


def test_plan_report_through_the_twin_confirms_the_plan(monkeypatch):
    import mec_app.app as app
    sent = []
    monkeypatch.setattr(app, "post", lambda c, b: sent.append(b))
    monkeypatch.setattr(app.engine.cfg, "plan_confirm", True, raising=False)
    monkeypatch.setattr(app.engine.cfg, "ack_s", 0.0, raising=False)
    alert = {"event": "raise", "forklift": "f9", "worker": "w9", "actions": {"f9": {"speed_limit": 1.2, "stop_at": [3, 0]}}}
    with app.lock:
        app.state["plans"]["wanted"][("f9", "w9")] = (0.0, alert)
    rep = {"egs:spdLt": {"rn": "speedLimit", "cnd": sdt.DEVICE["forklift"][5],
                         "lbl": ["egs:id/f9", "egs:role/forklift", "egs:module/speedLimit"],
                         **sdt.speed_limit_report([("w9", 1.2, True)])}}
    app.process_notification({"m2m:sgn": {"nev": {"rep": rep, "net": 1}, "sur": "x"}})
    assert ("f9", "w9") not in app.state["plans"]["wanted"] and not sent
