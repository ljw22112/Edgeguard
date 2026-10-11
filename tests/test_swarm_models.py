"""Swarm scheduling (edgeguard/swarm.py) and model delivery decisions (edgeguard/model_delivery.py)."""
import numpy as np

from edgeguard import fl
from edgeguard.model_delivery import FLPredictor, ModelManager, ModelRegistry
from edgeguard.swarm import conflicts, reactive_delays, schedule

P = [{"id": "a", "prio": 0, "route": [["I1", 6.0], ["I2", 14.0]]},
     {"id": "b", "prio": 0, "route": [["I1", 7.5]]},
     {"id": "c", "prio": 1, "route": [["I1", 6.5]]}]


def test_schedule_is_conflict_free_priority_first_and_order_independent():
    d = schedule(P)
    assert d["c"] == 0.0 and not conflicts(P, d)
    assert schedule(list(reversed(P))) == d


def test_reactive_baseline_costs_more():
    d = schedule(P)
    assert sum(d.values()) < sum(reactive_delays(P).values())


class FakeC:
    def __init__(self):
        self.status = []

    def update_fcnt(self, path, tp, attrs):
        self.status.append(attrs)


def models():
    X, Y = fl.site_data("busan", 240, seed=1)
    w, _ = fl.train(fl.init_weights(0), X, Y, epochs=8)
    return (X, Y), w


def test_canary_rejects_worse_than_constant_velocity_and_activates_better():
    hold, w = models()
    reg = ModelRegistry()
    m = ModelManager(FakeC(), "s", hold, registry=reg, log=lambda *a: None)
    assert m.on_model({"version": 0, "weights": fl.pack(fl.init_weights(0))}) == "rejected"
    assert m.on_model({"version": 1, "weights": fl.pack(w)}) == "active"
    assert reg.get()[0] == 1
    assert m.on_model({"version": 1, "weights": fl.pack(w)}) == "old"


def test_rollback_after_patience_windows():
    hold, w = models()
    reg = ModelRegistry()
    m = ModelManager(FakeC(), "s", hold, registry=reg, patience=2, log=lambda *a: None)
    m.on_model({"version": 1, "weights": fl.pack(w)})
    bad = {k: v * 1.0 for k, v in w.items()}
    m.active = (2, {k: v * 3.0 for k, v in bad.items()})       # force a bad active model, v1 as previous
    m.previous = (1, w)
    X, Y = hold
    assert not m.observe(X, Y).get("rolled_back")
    assert m.observe(X, Y).get("rolled_back")
    assert m.active[0] == 1 and reg.get()[0] == 1


def test_fl_predictor_interpolates_horizons():
    hist = np.array([[0.1 * i, 0.0] for i in range(fl.H_IN + 1)], dtype=np.float32)
    w = {k: np.zeros_like(v) for k, v in fl.init_weights(0).items()}         # zero residual = constant velocity
    p = FLPredictor(hist, w).positions([0.0, 1.0, 2.0, 3.0])
    assert np.allclose([q[0] for q in p], [0.8, 1.8, 2.8, 3.8], atol=1e-4)
