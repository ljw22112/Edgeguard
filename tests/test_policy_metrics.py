import pytest

from sim.closed_loop import EpisodeResult, score


def ep(conflict, first_alert=None, t_contact=None, actual=5.0, lost=0.0, nom=20.0, act=20.0):
    return EpisodeResult("x", conflict, t_contact, first_alert, 0.1 if conflict else 3.0, actual,
                         nom, act, lost, 0, 1 if first_alert is not None else 0)


def test_f_beta_and_reward():
    res = [
        ep(True, first_alert=3.0, t_contact=5.0),           # TP (2 s lead)
        ep(True, first_alert=4.5, t_contact=5.0),           # late -> FN
        ep(False, first_alert=2.0),                          # FP
        ep(False),                                           # TN
        ep(True, first_alert=1.0, t_contact=4.0, actual=0.5, lost=2.0, act=15.0),   # TP but collided
    ]
    s = score(res, beta=2.0, collision_penalty=10, w_time=1.0, w_fp=0.5)
    p, r = 2 / 3, 2 / 3
    assert s["precision"] == pytest.approx(p) and s["recall"] == pytest.approx(r)
    assert s["f_beta"] == pytest.approx(5 * p * r / (4 * p + r))
    assert s["collisions"] == 1 and s["false_alarms"] == 1
    assert s["throughput"] == pytest.approx(95 / 100)
    assert s["reward"] == pytest.approx(-(10 + 2.0 + 0.5) / 5)


def test_beta_weights_recall():
    # same TP, more misses vs more false alarms: beta=2 punishes misses harder
    misses = [ep(True, 3.0, 5.0)] + [ep(True, None, 5.0)] * 2
    false_alarms = [ep(True, 3.0, 5.0)] + [ep(False, 2.0)] * 2
    assert score(misses, beta=2)["f_beta"] < score(false_alarms, beta=2)["f_beta"]
    assert score(misses, beta=1)["f_beta"] == pytest.approx(score(false_alarms, beta=1)["f_beta"])
