"""MEC Sandbox alignment: scenario generator, scenario player (mec_mock), MEC-IPE content,
oneM2M discovery and the sparse-data debounce."""
import math
import os
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import sandbox_scenario as ss                                        # noqa: E402
from mec_ipe import rn_of                                            # noqa: E402

from edgeguard.alerting import AlertState                            # noqa: E402
from edgeguard.mec_services import SiteFrame, parse_user_info        # noqa: E402
from edgeguard.onem2m import OneM2MClient                            # noqa: E402
from mec_mock.scenario_player import ScenarioPlayer                  # noqa: E402

SITE = yaml.safe_load(open(os.path.join(ROOT, "config", "site.yaml")))
O = SITE["mec_services"]["origin"]
FRAME = SiteFrame(O["lat"], O["lon"])


def ues_of(sc):
    for dom in sc["deployment"]["domains"]:
        for z in dom["zones"]:
            for nl in z["networkLocations"]:
                for pl in nl.get("physicalLocations") or []:
                    if pl["type"] == "UE":
                        yield pl


def test_scenario_file_matches_generator_and_config():
    sc = ss.build(FRAME)
    assert sc["version"] == "1.8.0"
    names = {u["name"] for u in ues_of(sc)}
    assert names == {t[0] for t in ss.TRACKS.values()}
    for u in ues_of(sc):
        g = u["geoData"]
        assert g["path"]["type"] == "LineString" and g["eopMode"] in ("LOOP", "REVERSE") and g["velocity"] > 0
    committed = yaml.safe_load(open(os.path.join(ROOT, "scenarios", "edgeguard-warehouse.yaml")))
    assert committed == sc, "regenerate: python tools/sandbox_scenario.py"
    cfg_map = {k: v for k, v in SITE["mec_services"]["ue_map"].items()}
    assert cfg_map == ss.ue_map()


def test_player_moves_ues_along_tracks():
    p = ScenarioPlayer(ss.build(FRAME), period=0.0, t0=0.0)
    u = p.users(t=0.0)
    for dev, (addr, _, track, eop, v) in ss.TRACKS.items():
        x, y = FRAME.to_xy(u[addr]["lat"], u[addr]["lon"])
        assert math.hypot(x - track[0][0], y - track[0][1]) < 0.05, dev
    # worker_03: (22, 20) -> (22, 6) at 1.0 m/s, REVERSE: 4 s -> y = 16, 18 s -> back at y = 10
    a = ss.TRACKS["worker_03"][0]
    for t, y_exp in ((4.0, 16.0), (18.0, 10.0)):
        x, y = FRAME.to_xy(p.users(t=t)[a]["lat"], p.users(t=t)[a]["lon"])
        assert (x, y) == pytest.approx((22.0, y_exp), abs=0.05)
    assert p.users(t=4.0)[a]["zone"] == "warehouse-east"


def test_player_noise_is_fixed_within_a_period():
    p = ScenarioPlayer(ss.build(FRAME), period=1.0, t0=0.0, noise=1.0)
    a = ss.TRACKS["worker_01"][0]
    assert p.users(t=3.2)[a]["lat"] == p.users(t=3.9)[a]["lat"]     # one fix per period
    assert p.users(t=3.2)[a]["lat"] != p.users(t=4.1)[a]["lat"]


def test_ipe_content_parsing_and_names():
    lat, lon = FRAME.to_latlon(5.0, 7.0)
    for u in ({"address": "10.100.0.1", "locationInfo": {"latitude": [lat], "longitude": [lon], "accuracy": 2}},
              {"address": "10.100.0.1", "latitude": lat, "longitude": lon, "timestamp": 12.5}):
        info = parse_user_info(u, FRAME)
        assert (info["x"], info["y"]) == pytest.approx((5.0, 7.0), abs=1e-3)
    assert parse_user_info({"address": "x"}, FRAME) is None
    assert rn_of("10.100.0.1") == "ue_10_100_0_1"


@pytest.mark.parametrize("uri", ["Mobius/MEC-IPE/location/ue_1", "/Mobius2/Mobius/MEC-IPE/location/ue_1",
                                 "MEC-IPE/location/ue_1"])
def test_discover_normalises_paths(monkeypatch, uri):
    c = OneM2MClient("http://cse", "Mobius", "S", "2a")
    monkeypatch.setattr(c, "request", lambda *a, **k: {"m2m:uril": [uri]})
    assert c.discover("MEC-IPE/location") == ["MEC-IPE/location/ue_1"]


def test_debounce_counts_time_for_sparse_fixes():
    dense = AlertState(debounce=2)
    assert dense.step(2, 0.0) is None and dense.step(2, 0.1) == "raise"    # 10 Hz: two samples
    sparse = AlertState(debounce=2)
    assert sparse.step(2, 0.0) is None                                     # first ever sample
    sparse.step(0, 1.0)
    assert sparse.step(2, 2.0) == "raise"                                  # 1 Hz: one sample spans 0.2 s
