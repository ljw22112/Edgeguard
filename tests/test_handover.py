"""CSE handover (edgeguard/handover.py): zone geometry, hysteresis, interruption / loss metrics."""
from edgeguard.handover import HandoverEvent, Zone
from tools.handover_demo import metrics

A = Zone("A", "http://a", "cse-mn-a", "id-mn-a", (-60.0, -30.0, 0.0, 30.0))
B = Zone("B", "http://b", "cse-mn-b", "id-mn-b", (0.0, -30.0, 60.0, 30.0))


def test_zone_contains_with_hysteresis():
    assert A.contains(-5, 0) and not A.contains(0.5, 0)
    assert A.contains(0.5, 0, margin=-1.0)          # still served by A until 1 m past the border
    assert not A.contains(1.5, 0, margin=-1.0)
    assert B.contains(1.5, 0)


def test_zone_distance():
    assert A.distance(-5, 0) == 0.0
    assert abs(B.distance(-3, 0) - 3.0) < 1e-9


def test_metrics_gap_and_loss():
    ev = HandoverEvent("f", "A", "B", "location", t_start=10.0, t_switch=10.2)
    sent = [(i, "A", True, 9.5 + i * 0.1) for i in range(20)]
    rx = [(9.5 + i * 0.1 + 0.01, i, "x") for i in range(20) if i not in (8, 9)]   # two lost, 300 ms gap
    m = metrics(rx, sent, ev)
    assert m["samples_lost"] == 2 and 190 <= m["interruption_ms"] <= 210
