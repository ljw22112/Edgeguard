"""MEC mobility pieces without a CSE: radio model, scenario attach, network-triggered handover, IPE parsing."""
import os

from edgeguard.handover import HandoverClient, Zone
from edgeguard.mobility import MecIpe, MecServiceClient, rn_of, rsrp_dbm
from mec_mock.scenario_player import ScenarioPlayer, rsrp_index, rsrq_index

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_rsrp_reporting_range():
    assert rsrp_index(-44) == 97 and rsrp_index(-150) == 0 and rsrp_index(-90.4) == 50
    assert rsrp_dbm(50) == -91
    assert rsrq_index(-70, [-110]) > rsrq_index(-90, [-90])


def test_two_zone_scenario_attaches_to_the_nearest_cell():
    p = ScenarioPlayer.load(os.path.join(ROOT, "scenarios", "edgeguard-two-zones.yaml"), period=0.0, t0=0.0)
    assert p.users(1.0)["forklift_01"]["cell"] == "cellA"
    assert p.users(12.0)["forklift_01"]["cell"] == "cellB"
    r = p.radio(12.0)["forklift_01"]
    assert r["cellB"] > r["cellA"]


def zones():
    return [Zone("A", "http://a", "a", "id-a", (0, 0, 40, 30)), Zone("B", "http://b", "b", "id-b", (40, 0, 80, 30))]


def test_network_trigger_prepares_once(monkeypatch):
    hc = HandoverClient({}, "fk", "forklift", "S", zones(), trigger="network", log=lambda *a: None)
    hc.serving = "A"
    started = []
    monkeypatch.setattr(hc, "_prepare", lambda tgt, reason: (started.append((tgt, reason)), setattr(hc, "pending", {})))
    assert not hc.network_trigger("A")           # already serving
    assert hc.network_trigger("B")
    assert not hc.network_trigger("B")           # one preparation at a time
    assert started == [("B", "network")]


def test_network_mode_ignores_location():
    hc = HandoverClient({}, "fk", "forklift", "S", zones(), trigger="network", log=lambda *a: None)
    hc.serving = "A"
    hc.client = lambda z: type("C", (), {"publish": lambda self, p, s: None})()
    hc.publish({"x": 70.0, "y": 5.0, "ts": 1})
    assert hc.pending is None and hc.serving == "A"


class FakeCse:
    origin = "SMecIpe"

    def __init__(self):
        self.calls = []

    def create_cin(self, path, con):
        self.calls.append(("cin", path, con))

    def update_fcnt(self, path, tp, attrs):
        self.calls.append(("upd", path, tp, attrs))

    def create_fcnt(self, *a, **k):
        self.calls.append(("fcnt", a[0], a[2]))

    def set_acpi(self, *a, **k):
        pass


def ipe():
    i = MecIpe(FakeCse(), "http://mec", log=lambda *a: None)
    i.acp_read = ("MEC-IPE/acp", "ri")
    return i


def test_zone_event_written_as_content_instance_and_location_module():
    i = ipe()
    i.on_location_event({"zoneLocationEventNotification": {
        "notificationType": "ZoneLocationEventNotification", "address": "fk", "zoneId": "zoneB",
        "accessPointId": "poa-b", "userLocationEvent": "ENTERING_AREA_EVENT",
        "timeStamp": {"seconds": 10, "nanoSeconds": 500000000}}}, 11.0)
    cin = [c for c in i.c.calls if c[0] == "cin"][0]
    assert cin[1] == "MEC-IPE/zoneEvents" and cin[2]["zone"] == "zoneB" and cin[2]["mec_ts"] == 10500
    upd = [c for c in i.c.calls if c[0] == "upd"][0]
    assert upd[1] == f"MEC-IPE/{rn_of('fk')}/location" and upd[3]["zonId"] == "zoneB"


def test_meas_rep_becomes_radio_link_with_strongest_neighbour():
    i = ipe()
    i.on_meas_rep({"associateId": [{"type": "UE_IPv4_ADDRESS", "value": "fk"}], "ecgi": {"cellId": "cellA"},
                   "rsrp": 60, "rsrq": 20, "timeStamp": {"seconds": 1},
                   "eutranNeighbourCellMeasInfo": [{"ecgi": {"cellId": "c2"}, "rsrp": 30},
                                                   {"ecgi": {"cellId": "cellB"}, "rsrp": 45}]}, 1.0)
    upd = [c for c in i.c.calls if c[0] == "upd"][0]
    assert upd[2] == "egs:rdLnk" and upd[3]["srvCl"] == "cellA" and upd[3]["nbCl"] == "cellB" and upd[3]["nbRp"] == 45


def test_service_client_matches_response_by_rqi():
    c = FakeCse()
    svc = MecServiceClient(c)

    def create_cin(path, con):
        svc.on_response({"rqi": con["rqi"], "ok": True, "result": {"x": 1}})
    c.create_cin = create_cin
    r = svc.call("location", ue="fk", timeout=1)
    assert r["ok"] and r["result"] == {"x": 1}
