"""tools/sandbox_probe.py: vehicle/pedestrian classification from two Location API snapshots."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import sandbox_probe as sp                                                    # noqa: E402


def ue(addr, lat, lon):
    return {"address": addr, "locationInfo": {"latitude": [lat], "longitude": [lon]}}


def test_classify_by_speed():
    lat, lon = 43.7335, 7.4135
    d = 1e-5                                    # ~1.1 m of latitude
    s1 = {"a": ue("a", lat, lon), "b": ue("b", lat, lon + d), "c": ue("c", lat + d, lon)}
    s2 = {"a": ue("a", lat + 20 * d, lon),        # ~22 m in 4 s -> vehicle
          "b": ue("b", lat + 2 * d, lon + d),     # ~2 m in 4 s -> pedestrian
          "c": ue("c", lat + d, lon)}             # still
    kinds, (lat0, lon0) = sp.classify(s1, s2, 4.0, 3.0)
    assert kinds["a"][1] == "forklift" and kinds["a"][0] > 5
    assert kinds["b"][1] == "worker" and 0.3 < kinds["b"][0] < 1.0
    assert kinds["c"] == (0.0, "worker")
    assert abs(lat0 - lat) < 1e-4 and abs(lon0 - lon) < 1e-4


def test_latlon_scalar_and_missing():
    assert sp.latlon({"latitude": 1.5, "longitude": 2.5}) == (1.5, 2.5)
    assert sp.latlon({"locationInfo": {}}) is None
