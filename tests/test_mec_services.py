import pytest

from edgeguard.mec_services import LocationClient, RnisClient, SiteFrame


class _Resp:
    def __init__(self, body, code=200):
        self._b, self.status_code = body, code

    def json(self):
        return self._b


def test_site_frame_round_trip():
    f = SiteFrame(37.5503, 127.0731)
    lat, lon = f.to_latlon(12.0, -7.5)
    x, y = f.to_xy(lat, lon)
    assert x == pytest.approx(12.0, abs=1e-6) and y == pytest.approx(-7.5, abs=1e-6)


def test_location_user_parsing(monkeypatch):
    f = SiteFrame(37.5503, 127.0731)
    lat, lon = f.to_latlon(3.0, 4.0)
    c = LocationClient("http://mec", frame=f)
    body = {"userList": {"user": [{"address": "acr:1", "zoneId": "z1",
                                    "timestamp": {"seconds": 10, "nanoSeconds": 0},
                                    "locationInfo": {"latitude": [lat], "longitude": [lon], "accuracy": 2}}]}}
    monkeypatch.setattr(c.s, "get", lambda *a, **k: _Resp(body))
    u = c.user("acr:1")
    assert u["x"] == pytest.approx(3.0, abs=1e-3) and u["accuracy"] == 2 and u["zone"] == "z1"


def test_rnis_cell_load(monkeypatch):
    c = RnisClient("http://mec")
    body = {"cellInfo": [{"dl_gbr_prb_usage_cell": 40, "dl_nongbr_prb_usage_cell": 45,
                          "ul_gbr_prb_usage_cell": 5, "ul_nongbr_prb_usage_cell": 5}]}
    monkeypatch.setattr(c.s, "get", lambda *a, **k: _Resp(body))
    assert c.cell_load() == 85
