"""Zone groups and polling-channel parsing (edgeguard/zones.py) without a CSE."""
from unittest import mock

from edgeguard.zones import PollingReceiver, ZoneGroups


class FakeClient:
    cse_rn, origin, rvi = "cse-in", "SMec", "3"

    def __init__(self):
        self.calls = []

    def request(self, method, path, ty=None, body=None, ok_conflict=False, params=None):
        self.calls.append((method, path, ty, body))
        if path.endswith("/fopt"):
            return {"m2m:agr": {"m2m:rsp": [{"rsc": 2001}, {"rsc": 2001}, {"rsc": 4103}]}}
        return {}

    def url(self, path=""):
        return f"http://cse/{self.cse_rn}/{path}"


def zg():
    c = FakeClient()
    g = ZoneGroups(c, "EdgeGuard", {"A": (0, 0, 10, 10), "B": (10, 0, 20, 10)})
    for t in ("t1", "t2", "t3"):
        g.register_tag(t)
    return c, g


def test_setup_creates_one_group_per_zone_under_the_ae():
    c, g = zg()
    assert g.setup() == ["A", "B"]
    assert [(m, p, ty, b["m2m:grp"]["rn"]) for m, p, ty, b in c.calls] == [
        ("POST", "EdgeGuard", 9, "zone_A"), ("POST", "EdgeGuard", 9, "zone_B")]


def test_update_rewrites_only_changed_groups():
    c, g = zg()
    assert sorted(g.update({"t1": (1, 1), "t2": (2, 2), "t3": (15, 5)})) == ["A", "B"]
    assert g.members == {"A": {"t1", "t2"}, "B": {"t3"}}
    c.calls.clear()
    assert g.update({"t1": (1, 1), "t2": (2, 2), "t3": (15, 5)}) == []        # nothing moved
    assert c.calls == []
    assert sorted(g.update({"t1": (1, 1), "t2": (12, 2), "t3": (15, 5)})) == ["A", "B"]
    mids = {p: b["m2m:grp"]["mid"] for _, p, _, b in c.calls}
    assert mids["EdgeGuard/zone_B"] == ["cse-in/t2/alerts", "cse-in/t3/alerts"]


def test_unregistered_or_outside_tags_are_ignored():
    c, g = zg()
    g.update({"t1": (50, 50), "stranger": (1, 1)})
    assert g.members == {"A": set(), "B": set()}


def test_broadcast_is_one_request_and_counts_accepted_members():
    c, g = zg()
    assert g.broadcast("A", {"x": 1}) == 0                     # empty zone: no request
    g.update({"t1": (1, 1), "t2": (2, 2)})
    c.calls.clear()
    assert g.broadcast("A", {"x": 1}) == 2
    assert len(c.calls) == 1 and c.calls[0][:3] == ("POST", "EdgeGuard/zone_A/fopt", 4)


def test_polling_receiver_parses_notification_and_sends_the_response():
    got = []
    r = PollingReceiver(FakeClient(), "t1", lambda con, t: got.append(con))
    rqp = {"rqi": "abc", "pc": {"m2m:sgn": {"nev": {"net": 3, "rep": {"m2m:cin": {"con": '{"id": 7}'}}}}}}
    with mock.patch("edgeguard.zones.requests.post") as post:
        r._handle(rqp, "http://cse/cse-in/t1/pch/pcu")
    assert got == [{"id": 7}]
    body = post.call_args.kwargs["data"]
    assert '"rqi": "abc"' in body and '"rsc": 2000' in body


def test_polling_receiver_ignores_non_content_notifications():
    got = []
    r = PollingReceiver(FakeClient(), "t1", lambda con, t: got.append(con))
    with mock.patch("edgeguard.zones.requests.post"):
        r._handle({"rqi": "x", "pc": {"m2m:sgn": {"vrq": True}}}, "u")
    assert got == []
