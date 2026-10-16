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
    import tempfile
    # never talk to a real CSE from unit tests: the app's self-healing would create resources there
    over = os.path.join(tempfile.mkdtemp(), "no-cse.yaml")
    with open(over, "w") as fh:
        fh.write("cse: {base_url: 'http://127.0.0.1:9', cse_rn: cse-test}\ncloud_sync: {enabled: false}\n")
    prev = os.environ.get("EDGEGUARD_OVERRIDES")
    os.environ["EDGEGUARD_OVERRIDES"] = over
    import importlib
    import mec_app.app as m
    yield importlib.reload(m)
    if prev is None:
        os.environ.pop("EDGEGUARD_OVERRIDES", None)
    else:
        os.environ["EDGEGUARD_OVERRIDES"] = prev


def test_bad_notifications_answer_2000(app_mod):
    from fastapi.testclient import TestClient
    c = TestClient(app_mod.app)
    before = app_mod.state["input"]["bad"]
    r = c.post("/notify", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 200 and r.headers["X-M2M-RSC"] == "2000"
    sgn = {"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": {"id": "w9", "kind": "worker", "x": "a", "y": 1}}}}}}
    assert c.post("/notify", json=sgn).status_code == 200
    deadline = time.time() + 2.0                          # samples are processed by the ingest worker
    while app_mod.state["input"]["bad"] < before + 2 and time.time() < deadline:
        time.sleep(0.02)
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


def test_sitemap_line_of_sight_and_occluded_margin():
    from edgeguard.sitemap import SiteMap
    from edgeguard.risk import RiskConfig, assess
    from edgeguard.tracking import Track
    m = SiteMap([[-40, -40, -1.6, -1.6]])
    assert m.blocked((-8, 0), (0, -8)) and not m.blocked((-2, 0), (0, -2)) and not m.blocked((-8, 0), (8, 0))
    w, f = Track("w", "worker"), Track("f", "forklift")
    for k in range(5):                                   # worker passes 1.85 m from the forklift's path
        w.update(0.1 * k, 1.85, -6 + 0.1 * k)
        f.update(0.1 * k, -6 + 0.2 * k, 0.0, speed=2.0, heading=0.0, yaw_rate=0.0)
    cfg = RiskConfig()
    plain, occl = assess(w, f, cfg), assess(w, f, cfg, occluded=True)
    assert occl.occluded and occl.level >= plain.level


def test_ingest_coalesces_a_devices_waiting_samples(app_mod):
    """Under overload only the newest waiting sample of a device is processed (bounded delay)."""
    before = app_mod.state["ingest"]["coalesced"]
    with app_mod._ingest_cv:                              # re-entrant: the worker waits while we queue 5 samples
        for x in range(5):
            app_mod.enqueue({"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": {
                "id": "w_coal", "kind": "worker", "x": float(x), "y": 0.0}}}}}})
    assert app_mod.state["ingest"]["coalesced"] == before + 4
    deadline = time.time() + 2.0
    while time.time() < deadline and "w_coal" not in app_mod.engine.tracks:
        time.sleep(0.02)
    assert abs(app_mod.engine.tracks["w_coal"].pos[0] - 4.0) < 1e-6     # only the newest sample was used


def test_supervised_loop_restarts_after_an_exception(app_mod):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        time.sleep(30)
    app_mod.supervise("test_flaky", flaky, period=60)
    deadline = time.time() + 3.0
    while len(calls) < 2 and time.time() < deadline:
        time.sleep(0.05)
    st = app_mod.loops_status()["test_flaky"]
    assert len(calls) == 2 and st["restarts"] == 1 and "boom" in st["last_error"]


def test_publisher_rebuilds_its_tree_when_the_cse_lost_it(app_mod, monkeypatch):
    from edgeguard.onem2m import OneM2MError
    made, sent = [], []
    state = {"gone": True}

    def create_cin(path, con):
        if state["gone"]:
            raise OneM2MError(404, "4004", "No resource with this ID", path)
        sent.append(path)
    monkeypatch.setattr(app_mod.cse, "create_cin", create_cin)
    monkeypatch.setattr(app_mod.cse, "create_ae", lambda *a, **k: (made.append("ae"), state.update(gone=False)))
    monkeypatch.setattr(app_mod.cse, "create_container", lambda *a, **k: made.append(a[1]))
    monkeypatch.setattr(app_mod.cse, "create_subscription", lambda *a, **k: None)
    app_mod._tree_last[0] = 0.0
    app_mod.post("alert", {"event": "warn"})
    deadline = time.time() + 3.0
    while not sent and time.time() < deadline:
        time.sleep(0.02)
    assert "ae" in made and "alert" in made and sent and sent[-1].endswith("/alert")


def test_gc_drops_side_tables_of_forgotten_tracks(app_mod):
    from edgeguard.worker_cue import WaitCue
    app_mod.handle_sample({"id": "untagged_gc", "kind": "worker", "x": 50.0, "y": 50.0})
    app_mod.state["worker_cue"]["untagged_gc"] = WaitCue()
    app_mod.state["worker_aside"]["untagged_gc"] = time.time()
    app_mod.gc_once(now=time.monotonic() + app_mod.GC_S + 1)
    assert "untagged_gc" not in app_mod.state["worker_cue"] and "untagged_gc" not in app_mod.state["worker_aside"]
