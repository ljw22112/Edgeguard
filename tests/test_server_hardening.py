"""MEC app hardening (v0.9): late samples, bad input, stale outbox entries, GC, metrics."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from edgeguard.tracking import Track   # noqa: E402


def test_late_sample_does_not_reset_the_track():
    t = Track("w", "worker")
    for k in range(10):
        t.update(0.1 * k, 0.1 * k, 0.0)
    v = t.vel
    assert t.update(0.75, 0.75, 0.0) is False            # arrived after the 0.9 s sample
    assert t.x is not None and t.vel == v and t.dropped_late == 1
    assert t.update(0.0, 5.0, 0.0) is False or t.x is not None
    t.update(-5.0, 5.0, 0.0)                              # clock went far back: device restart
    assert t.pos == (5.0, 0.0)


@pytest.fixture(scope="module")
def app_mod():
    pytest.importorskip("fastapi")
    os.environ.setdefault("EDGEGUARD_OVERRIDES", "")
    import importlib
    import mec_app.app as m
    return importlib.reload(m)


def test_bad_notifications_answer_2000(app_mod):
    from fastapi.testclient import TestClient
    c = TestClient(app_mod.app)
    before = app_mod.state["input"]["bad"]
    r = c.post("/notify", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 200 and r.headers["X-M2M-RSC"] == "2000"
    sgn = {"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": {"id": "w9", "kind": "worker", "x": "a", "y": 1}}}}}}
    assert c.post("/notify", json=sgn).status_code == 200
    assert app_mod.state["input"]["bad"] >= before + 2


def test_clock_skew_uses_arrival_time(app_mod):
    before = app_mod.state["input"]["clock_skew"]
    app_mod.handle_sample({"id": "w_skew", "kind": "worker", "x": 1.0, "y": 1.0, "ts": 1})   # 1970
    assert app_mod.state["input"]["clock_skew"] == before + 1
    assert "w_skew" in app_mod.engine.tracks


def test_stale_outbox_entries_are_dropped(app_mod, monkeypatch):
    calls = []
    monkeypatch.setattr(app_mod.cse, "create_cin", lambda path, con: calls.append(con))
    app_mod.outbox.put((1, -1, time.monotonic() - 10.0, "control", "x/control", {"hb": True}))
    deadline = time.time() + 2.0
    while app_mod.outbox.qsize() and time.time() < deadline:
        time.sleep(0.02)
    assert {"hb": True} not in calls and app_mod.state["publisher"]["dropped_stale"] >= 1


def test_gc_forgets_silent_tracks_and_pairs(app_mod):
    app_mod.handle_sample({"id": "w_gc", "kind": "worker", "x": 0.0, "y": 0.0})
    app_mod.handle_sample({"id": "f_gc", "kind": "forklift", "x": 3.0, "y": 0.0, "speed": 1.0, "heading": 3.14, "yaw_rate": 0.0})
    gone = app_mod.gc_once(now=time.monotonic() + app_mod.GC_S + 1)
    assert "w_gc" in gone and "f_gc" in gone
    assert all("w_gc" not in k and "f_gc" not in k for k in app_mod.state["pairs"])


def test_metrics_and_health(app_mod):
    from fastapi.testclient import TestClient
    c = TestClient(app_mod.app)
    m = c.get("/metrics").text
    assert "edgeguard_publish_dropped_stale_total" in m and "edgeguard_tracks" in m
    h = c.get("/health").json()
    assert "degraded" in h and "publisher" in h and "input" in h
