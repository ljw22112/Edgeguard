"""MEC 011 / 021 / 013-geofence: the mock platform router and the EdgeGuard clients, without a network."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edgeguard import mec_platform
from edgeguard.mec_platform import AmsClient, Mp1Client
from mec_mock import platform

LAT0, LON0 = 37.4979, 127.0276
K = 111319.49                      # metres per degree of latitude (WGS84 equatorial radius, as in the mock)


def lonlat(x, y):
    import math
    return LON0 + x / (K * math.cos(math.radians(LAT0))), LAT0 + y / K


@pytest.fixture()
def mec(monkeypatch):
    for d in (platform.SERVICES, platform.READY, platform.SER_SUBS, platform.AMS_REG, platform.AMS_SUBS,
              platform.GEO_SUBS):
        d.clear()
    platform.LOG.clear()
    users, sent = {}, []
    platform.init(lambda: users, lambda url, body: sent.append((url, body)), {"zoneA": "mep-a", "zoneB": "mep-b"}, loop=False)
    app = FastAPI()
    app.include_router(platform.router)
    tc = TestClient(app)

    class Shim:                    # requests.<verb>(url, ...) -> TestClient, so the real clients run unchanged
        def __getattr__(self, verb):
            return lambda url, **kw: getattr(tc, verb)(url.replace("http://mec", ""),
                                                       **{k: v for k, v in kw.items() if k != "timeout"})
    monkeypatch.setattr(mec_platform, "requests", Shim())

    def put(name, x, y, zone):
        lon, lat = lonlat(x, y)
        users[name] = {"lon": lon, "lat": lat, "zone": zone}
    return {"tc": tc, "sent": sent, "put": put, "last": {}}


def test_mp1_ready_register_discover_availability(mec):
    a = Mp1Client("http://mec", "edgeguard-a")
    a.confirm_ready()
    assert "edgeguard-a" in platform.READY
    assert a.endpoint("LocationService") == "/location/v3" and a.endpoint("AppMobilityService") == "/amsi/v1"
    a.subscribe_availability("http://cb/ser", names=["edgeguard-safety"])
    a.register_service("edgeguard-safety", "http://a/api", onem2m={"cseId": "id-mn-a", "ae": "SEdgeGuard"})
    a.register_service("other", "http://a/other")
    found = a.discover("edgeguard-safety")
    assert len(found) == 1 and found[0]["transportInfo"]["implSpecificInfo"]["oneM2M"]["cseId"] == "id-mn-a"
    assert "_app" not in found[0]
    a.deregister_service("edgeguard-safety")
    assert a.discover("edgeguard-safety") == []
    changes = [b["serviceReferences"][0]["changeType"] for u, b in mec["sent"] if u == "http://cb/ser"]
    assert changes == ["ADDED", "REMOVED"]          # 'other' is filtered out by serNames


def test_ams_moveout_trigger_and_completion(mec):
    a, b = AmsClient("http://mec", "edgeguard-a", "mep-a"), AmsClient("http://mec", "edgeguard-b", "mep-b")
    a.register(["fk"])
    b.register(["fk"], comm=("10.0.0.2", 9000))
    href = a.subscribe("http://cb/a")
    assert href.startswith("/amsi/v1/subscriptions/")
    mec["put"]("fk", 30, 10, "zoneA")
    platform.step(mec["last"])
    assert not mec["sent"]                          # first sighting: no move
    mec["put"]("fk", 45, 10, "zoneB")
    platform.step(mec["last"])
    (url, n), = mec["sent"]
    assert url == "http://cb/a" and n["mobilityStatus"] == "INTERHOST_MOVEOUT_TRIGGERED"
    assert n["targetAppInfo"]["appInstanceId"] == "edgeguard-b"
    assert n["targetAppInfo"]["commInterface"]["ipAddresses"][0] == {"host": "10.0.0.2", "port": 9000}
    a.context_transferred("fk")
    assert mec["sent"][-1][1]["mobilityStatus"] == "INTERHOST_MOVEOUT_COMPLETED"
    # a's subscription filters on its own instance: b's move back is not sent to a
    mec["put"]("fk", 30, 10, "zoneA")
    platform.step(mec["last"])
    assert len(mec["sent"]) == 2


def test_ams_same_host_is_not_a_moveout(mec):
    platform._ctx["host_of_zone"] = {"zoneA": "mep-a", "zoneB": "mep-a"}
    a = AmsClient("http://mec", "edgeguard-a", "mep-a")
    a.register(["fk"])
    a.subscribe("http://cb/a")
    mec["put"]("fk", 30, 10, "zoneA")
    platform.step(mec["last"])
    mec["put"]("fk", 45, 10, "zoneB")
    platform.step(mec["last"])
    assert not mec["sent"]


def test_area_enter_leave_and_distance(mec):
    lon, lat = lonlat(60, 10)
    tc = mec["tc"]
    r = tc.post("/location/v3/subscriptions/area", json={"userAreaSubscription": {
        "callbackReference": {"notifyURL": "http://cb/area"}, "addressList": ["fk"],
        "areaDefine": {"shape": 1, "points": [{"latitude": lat, "longitude": lon}], "radius": 6},
        "locationEventCriteria": ["ENTERING_AREA_EVENT", "LEAVING_AREA_EVENT"]}})
    area_href = r.json()["userAreaSubscription"]["_links"]["self"]["href"]
    tc.post("/location/v3/subscriptions/distance", json={"userDistanceSubscription": {
        "callbackReference": {"notifyURL": "http://cb/dist"}, "monitoredAddress": ["w1", "fk"], "distance": 5}})
    mec["put"]("w1", 30, 12, "zoneA")
    events = []
    for x in range(20, 75, 1):
        mec["put"]("fk", x, 10, "zoneA" if x < 40 else "zoneB")
        n0 = len(mec["sent"])
        platform.step(mec["last"])
        events += [(x, u, b) for u, b in mec["sent"][n0:]]
    area = [(x, b["userAreaNotification"]["userLocationEvent"]) for x, u, b in events if u == "http://cb/area"]
    dist = [(x, b["userDistanceNotification"]["distanceEvent"]) for x, u, b in events if u == "http://cb/dist"]
    assert area == [(54, "ENTERING_AREA_EVENT"), (67, "LEAVING_AREA_EVENT")]
    assert dist == [(26, "ALL_WITHIN_DISTANCE")]    # once on entering 5 m, not again while within
    tc.delete(area_href)
    assert len(platform.GEO_SUBS) == 1
