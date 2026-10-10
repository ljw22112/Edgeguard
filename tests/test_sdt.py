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
