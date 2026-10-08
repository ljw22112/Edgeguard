"""Active-standby lease: one leader, take-over after the leader stops, no flapping."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from edgeguard.ha import Lease   # noqa: E402


class FakeCSE:
    def __init__(self):
        self.cins = []
        self.down = False

    def latest(self, path):
        if self.down:
            raise ConnectionError("CSE down")
        return self.cins[-1] if self.cins else None

    def create_cin(self, path, con):
        if self.down:
            raise ConnectionError("CSE down")
        self.cins.append(con)


def test_single_leader_and_takeover_time():
    cse = FakeCSE()
    a, b = Lease(cse, "x", "mec-a", 1.0, 0.3), Lease(cse, "x", "mec-b", 1.0, 0.3)
    t = 0.0
    leaders = []
    for _ in range(20):                       # both running: exactly one leader at every step
        a.step(t)
        b.step(t + 0.15)
        leaders.append((a.leader, b.leader))
        t += 0.3
    assert all(x != y for x, y in leaders[2:])
    first = "a" if a.leader else "b"
    dead, alive = (a, b) if first == "a" else (b, a)
    t_dead = t
    while not alive.leader:                   # the leader crashes: only the other one steps
        alive.step(t)
        t += 0.3
        assert t - t_dead < 3.0
    assert t - t_dead <= 1.0 + 2 * 0.3 + 1e-6  # lease_s + about one renew period
    assert alive.stats["took_over"] >= 1


def test_cse_outage_does_not_make_two_leaders():
    cse = FakeCSE()
    a, b = Lease(cse, "x", "mec-a", 1.0, 0.3), Lease(cse, "x", "mec-b", 1.0, 0.3)
    for k in range(5):
        a.step(k * 0.3)
        b.step(k * 0.3 + 0.1)
    cse.down = True
    for k in range(5, 12):
        a.step(k * 0.3)
        b.step(k * 0.3 + 0.1)
    assert not (a.leader and b.leader)
    cse.down = False
    for k in range(12, 20):
        a.step(k * 0.3)
        b.step(k * 0.3 + 0.1)
    assert a.leader != b.leader


def test_with_retry_passes_keywords():
    """setup_resources creates containers with mni=... through with_retry."""
    from edgeguard.onem2m import OneM2MClient
    c = OneM2MClient.__new__(OneM2MClient)
    got = {}
    assert c.with_retry(lambda parent, rn, mni=200: got.update(mni=mni) or "ok", "ae", "x", mni=20) == "ok"
    assert got["mni"] == 20
