"""Host selection and timestamps of the orchestrator (edgeguard/orchestration.py) without a CSE."""
import datetime as dt
import time

from edgeguard.orchestration import Orchestrator, lt_age


def host(name, zone, cpu, rtt, age=0.5, st="up", mem=4096):
    return {"hstNm": name, "zone": zone, "cpuFr": cpu, "memFr": mem, "rttMs": rtt, "hstSt": st, "_age": age,
            "lcmUr": f"http://{name}"}


def orch(hosts):
    o = Orchestrator.__new__(Orchestrator)
    o.hb_timeout = 2.5
    o.hosts = lambda: hosts
    return o


H = [host("a1", "A", 4, 2), host("a2", "A", 2, 4), host("cloud", "", 16, 25), host("b1", "B", 8, 1)]


def test_zone_and_latency_first():
    assert [h["hstNm"] for h in orch(H).select({"zone": "A", "cpuMn": 2, "maxLt": 10})] == ["a1", "a2"]


def test_any_zone_respects_resources_and_latency():
    assert [h["hstNm"] for h in orch(H).select({"cpuMn": 8, "maxLt": 100})] == ["b1", "cloud"]
    assert orch(H).select({"cpuMn": 64}) == []


def test_stale_or_down_or_excluded_hosts_are_skipped():
    hs = [host("a1", "A", 4, 2, age=5.0), host("a2", "A", 4, 3, st="down"), host("a3", "A", 4, 4)]
    assert [h["hstNm"] for h in orch(hs).select({"zone": "A"})] == ["a3"]
    assert orch(hs).select({"zone": "A"}, exclude={"a3"}) == []


def test_lt_age():
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=3)
    lt = now.strftime("%Y%m%dT%H%M%S") + ",%06d" % now.microsecond
    assert 2.5 < lt_age(lt) < 4.0


def test_container_instance_runs_one_container_with_limits(monkeypatch):
    from edgeguard import orchestration as o
    calls = []

    class R:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def run(cmd, **kw):
        calls.append(cmd)
        return R(0, "abc123\n")
    monkeypatch.setattr(o.subprocess, "run", run)
    c = o.ContainerInstance("img:1", ("http://127.0.0.1:8080", "cse-in"), "edgeguard-risk", "r1", "host-a1", 9411,
                            "SEGOrch", cpu=2, mem_mb=512).start()
    cmd = calls[0]
    assert cmd[:3] == ["docker", "run", "-d"] and "--network" in cmd and "host" in cmd
    assert "edgeguard.host=host-a1" in cmd and "--memory" in cmd and "512m" in cmd
    assert cmd[cmd.index("img:1") + 1:] == ["--cse", "http://127.0.0.1:8080/cse-in", "--name", "edgeguard-risk",
                                            "--instance", "r1", "--host", "host-a1", "--port", "9411",
                                            "--orchestrator", "SEGOrch"]
    assert c.container_id == "abc123" and c.ae == "app-r1" and c.origin == "Sr1"
    c.terminate()
    assert calls[-1] == ["docker", "rm", "-f", "eg-r1"]
