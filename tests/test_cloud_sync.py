import time

from edgeguard.cloud_sync import CloudSync


class FakeCSE:
    def __init__(self):
        self.online = True
        self.received = []

    def create_ae(self, rn):
        if not self.online:
            raise ConnectionError("down")

    def create_container(self, parent, rn, mni=0):
        if not self.online:
            raise ConnectionError("down")

    def create_cin(self, path, con):
        if not self.online:
            raise ConnectionError("down")
        self.received.append((path, con["n"]))


def wait(cond, timeout=8.0):
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        time.sleep(0.02)
    return cond()


def test_outage_is_buffered_and_flushed_in_order():
    cse = FakeCSE()
    cs = CloudSync(cse, "Site", capacity=100, max_backoff=0.2)
    cs.put("alert", {"n": 0})
    assert wait(lambda: len(cse.received) == 1)
    cse.online = False                                    # WAN outage
    for n in range(1, 21):
        cs.put("alert" if n % 2 else "risk", {"n": n})
    time.sleep(0.5)
    assert cs.stats["online"] is False and cs.stats["backlog"] == 20
    cse.online = True                                     # WAN back
    assert wait(lambda: len(cse.received) == 21)
    assert [n for _, n in cse.received] == list(range(21))   # nothing lost, order kept
    assert cs.stats["dropped"] == 0


def test_full_backlog_drops_risk_before_alerts():
    cse = FakeCSE()
    cse.online = False
    cs = CloudSync(cse, "Site", capacity=5, max_backoff=0.2)
    for n in range(5):
        cs.put("risk", {"n": n})
    for n in range(5, 10):
        cs.put("alert", {"n": n})
    assert cs.stats["dropped"] == 5
    cse.online = True
    assert wait(lambda: len(cse.received) == 5)
    assert all(p.endswith("/alert") for p, _ in cse.received)
