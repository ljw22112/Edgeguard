"""Federated learning (edgeguard/fl.py): FedAvg, weight transport, local training, client selection."""
import numpy as np

from edgeguard import fl


def test_fedavg_is_sample_weighted():
    a = {k: np.zeros_like(v) for k, v in fl.init_weights(0).items()}
    b = {k: np.ones_like(v) for k, v in a.items()}
    m = fl.fedavg([(1, a), (3, b)])
    assert all(np.allclose(v, 0.75) for v in m.values())


def test_pack_round_trip():
    w = fl.init_weights(3)
    back = fl.unpack(fl.pack(w))
    assert all(np.array_equal(w[k], back[k]) for k in w)


def test_local_training_beats_constant_velocity():
    X, Y = fl.site_data("seoul", 360, seed=1)
    Xt, Yt = fl.site_data("seoul", 240, seed=2)
    w, _ = fl.train(fl.init_weights(0), X, Y, epochs=15)
    assert fl.ade(w, Xt, Yt) < 0.95 * fl.ade(None, Xt, Yt)


def test_selection_skips_unavailable_and_rotates():
    c = fl.Coordinator(cse=None, notify_url="", cpr=2, min_samples=100)
    parts = [{"ae": "a", "avail": True, "smpCt": 500, "cmpSc": 1.0},
             {"ae": "b", "avail": True, "smpCt": 500, "cmpSc": 0.9},
             {"ae": "c", "avail": True, "smpCt": 500, "cmpSc": 0.8},
             {"ae": "d", "avail": False, "smpCt": 900, "cmpSc": 1.0},
             {"ae": "e", "avail": True, "smpCt": 50, "cmpSc": 1.0}]
    first, _ = c.select(parts)
    second, _ = c.select(parts)
    assert first == ["a", "b"] and "c" in second           # the one that waited goes next
    assert not {"d", "e"} & set(first + second)            # offline / too little data: never
