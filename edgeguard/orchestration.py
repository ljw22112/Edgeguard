"""MEC application orchestration across MEC hosts, driven through oneM2M (TR-0077 federation & orchestration).

Everything the orchestrator needs to know and decide is a oneM2M resource, so any oneM2M application can
read where EdgeGuard runs, and an operator deploys by creating ONE resource:

  <host AE>/host                 egs:mecHs   each MEC host registers itself: zone, free CPU / memory, RTT to
                                             the site, its lifecycle API; heartbeat = update every second
  EGOrch/intent_<name>           egs:depIn   deployment intent: app, zone, CPU / memory, max latency; the
                                             orchestrator writes status, placement and the app's AE into it
  <app AE>                       the deployed instance registers itself (lbl egs:app/<name>)
    config                       CNT  the orchestrator provisions it: which device data to subscribe to
    status                       CNT  heartbeat and work counter of the running instance

Lifecycle per intent: discover hosts (label discovery) -> select (constraints, then lowest RTT and most
free CPU) -> deploy (host lifecycle API, MEC 010-2 style) -> register (the instance creates its AE) ->
provision (device ACPs extended to the instance, config written) -> running (first status) -> monitor:
host heartbeat lost -> re-placed on the next best host, grants of the old instance revoked.
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from .onem2m import ALL_OPS, CREATE, NOTIFY, RETRIEVE, DISCOVERY, OneM2MClient, OneM2MError, parse_notification

HOST_TP, INTENT_TP = "egs:mecHs", "egs:depIn"
HOST_CND = "org.edgeguard.safety.moduleclass.mecHost"
INTENT_CND = "org.edgeguard.safety.moduleclass.deploymentIntent"
ORCH_AE = "EGOrch"


def lt_age(lt: str) -> float:
    """Seconds since a oneM2M timestamp (UTC, 20261011T044702,905126)."""
    t = dt.datetime.strptime(lt.split(",")[0], "%Y%m%dT%H%M%S").replace(tzinfo=dt.timezone.utc)
    frac = float("0." + lt.split(",")[1]) if "," in lt else 0.0
    return time.time() - (t.timestamp() + frac)


# --- the deployed application ---------------------------------------------------------------------------
class EdgeApp:
    """A deployed EdgeGuard application instance: registers, waits for provisioning, then processes the
    device data it was told to subscribe to and reports a heartbeat with its work counter."""

    def __init__(self, cse: tuple, name, instance, host, port, orchestrator):
        self.name, self.instance, self.host = name, instance, host
        self.origin = f"S{instance}"
        self.c = OneM2MClient(cse[0], cse[1], self.origin, timeout=2.0)
        self.ae = f"app-{instance}"
        self.port, self.orch = port, orchestrator
        self.processed, self.provisioned = 0, threading.Event()
        self.stop = threading.Event()
        self.srv = None

    def start(self):
        app = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                self.send_response(200)
                self.send_header("X-M2M-RSC", "2000")
                self.end_headers()
                kind, con = parse_notification(body)
                if kind != "cin":
                    return
                if self.path == "/config" and isinstance(con, dict):
                    threading.Thread(target=app.provision, args=(con,), daemon=True).start()
                elif self.path == "/data":
                    app.processed += 1
                else:
                    app.on_notify(self.path, con)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        threading.Thread(target=self._register, daemon=True).start()
        return self

    def _register(self):
        c = self.c
        c.create_ae(self.ae, api=f"Nedgeguard.{self.name}", poa=[f"http://127.0.0.1:{self.port}"],
                    lbl=[f"egs:app/{self.name}", f"egs:host/{self.host}", f"egs:instance/{self.instance}"])
        c.create_container(self.ae, "config", mni=5)
        c.create_container(self.ae, "status", mni=20)
        acp = c.create_acp(self.ae, "acp_app", [([self.origin], ALL_OPS),
                                                ([self.orch], RETRIEVE | DISCOVERY | NOTIFY | CREATE)], [self.origin])
        for cnt in ("config", "status"):
            c.set_acpi(f"{self.ae}/{cnt}", f"{self.ae}/acp_app", acp.get("ri"))
        c.create_subscription(f"{self.ae}/config", "sub_self", [f"http://127.0.0.1:{self.port}/config"])
        threading.Thread(target=self._heartbeat, daemon=True).start()
        try:                                     # configuration written before the subscription existed
            cfg = c.latest(f"{self.ae}/config")
            if isinstance(cfg, dict) and not self.provisioned.is_set():
                self.provision(cfg)
        except OneM2MError:
            pass

    def provision(self, cfg):
        for path in cfg.get("subscribe", []):
            self.c.with_retry(self.c.create_subscription, path, f"sub_{self.instance}",
                              [f"http://127.0.0.1:{self.port}/data"], acpi=cfg.get("sub_acpi"))
        self.on_provision(cfg)
        self.provisioned.set()

    # hooks for application kinds built on this lifecycle (edgeguard/fl_app.py)
    def on_provision(self, cfg):
        pass

    def on_notify(self, path, con):
        pass

    def status_extra(self) -> dict:
        return {}

    def _heartbeat(self):
        while not self.stop.wait(1.0 if self.provisioned.is_set() else 0.2):
            if self.provisioned.is_set():
                try:
                    self.c.create_cin(f"{self.ae}/status", {"instance": self.instance, "host": self.host,
                                                            "processed": self.processed, "ts": int(time.time() * 1000),
                                                            **self.status_extra()})
                except Exception:
                    pass

    def terminate(self):
        self.stop.set()
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()


def app_class(name):
    """Application kind by app name: the federated-learning client (needs numpy) or the generic edge app."""
    if name == "edgeguard-fl":
        from .fl_app import FlEdgeApp
        return FlEdgeApp
    return EdgeApp


class ContainerInstance:
    """The same application instance as a container on the MEC host (image deploy/edge-app/Dockerfile).  The
    container registers its own AE exactly like the in-process EdgeApp; the host agent only runs and stops it."""

    def __init__(self, image, cse: tuple, name, instance, host, port, orchestrator, cpu=1.0, mem_mb=256):
        self.image, self.cse, self.name, self.instance, self.host = image, cse, name, instance, host
        self.port, self.orch, self.cpu, self.mem = port, orchestrator, cpu, mem_mb
        self.origin, self.ae, self.cname = f"S{instance}", f"app-{instance}", f"eg-{instance}"
        self.c = OneM2MClient(cse[0], cse[1], self.origin, timeout=2.0)
        self.container_id = None

    def start(self):
        cpus = max(0.1, min(float(self.cpu or 1.0), float(os.cpu_count() or 1)))
        base = ["docker", "run", "-d", "--rm", "--network", "host", "--name", self.cname,
                "--label", f"edgeguard.host={self.host}", "--label", f"edgeguard.instance={self.instance}",
                "--label", f"edgeguard.app={self.name}"]
        args = [self.image, "--cse", f"{self.cse[0]}/{self.cse[1]}", "--name", self.name, "--instance", self.instance,
                "--host", self.host, "--port", str(self.port), "--orchestrator", self.orch]
        limits = ["--cpus", f"{cpus:g}", "--memory", f"{max(64, int(self.mem or 256))}m"]
        r = subprocess.run(base + limits + args, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:                          # a daemon without cgroup limits: run unconstrained
            r = subprocess.run(base + args, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"docker run failed: {r.stderr.strip()[:200]}")
        self.container_id = r.stdout.strip()
        return self

    def terminate(self):
        subprocess.run(["docker", "rm", "-f", self.cname], capture_output=True, timeout=30)


# --- a MEC host -----------------------------------------------------------------------------------------
class MecHostAgent:
    """A MEC host: lifecycle API for app instances (instantiate / query / terminate) and self-registration
    in oneM2M as an egs:mecHs resource with a one-second heartbeat."""

    _ids = itertools.count(1)

    def __init__(self, cse: tuple, name, zone, cpu, mem_mb, rtt_ms, port, app_ports, runtime="thread",
                 image="edgeguard/edge-app:1.0"):
        """runtime: "thread" (instance in this process) or "docker" (one container per instance, `image`)."""
        self.cse, self.name, self.zone, self.cpu, self.mem, self.rtt = cse, name, zone, cpu, mem_mb, rtt_ms
        self.runtime, self.image = runtime, image
        self.port, self.app_ports = port, iter(app_ports)
        self.origin = f"S{name.replace('-', '')}"
        self.c = OneM2MClient(cse[0], cse[1], self.origin, timeout=2.0)
        self.instances: dict[str, tuple[EdgeApp, dict]] = {}
        self.stop, self.srv = threading.Event(), None

    def free(self):
        used = [r for _, r in self.instances.values()]
        return self.cpu - sum(r["cpu"] for r in used), self.mem - sum(r["mem"] for r in used)

    def start(self, readers=()):
        c = self.c
        c.create_ae(self.name, api="Nmec-host", lbl=["egs:mec/host", f"egs:zone/{self.zone or 'none'}"])
        c.create_fcnt(self.name, HOST_TP, "host", HOST_CND, self._attrs(), lbl=["egs:mec/host"])
        acp = c.create_acp(self.name, "acp_host", [([self.origin], ALL_OPS), (list(readers), RETRIEVE | DISCOVERY | NOTIFY)],
                           [self.origin])
        c.set_acpi(f"{self.name}/host", f"{self.name}/acp_host", acp.get("ri"), tp=HOST_TP)
        self._serve()
        threading.Thread(target=self._heartbeat, daemon=True).start()
        return self

    def _attrs(self):
        cpu, mem = self.free()
        return {"hstNm": self.name, "zone": self.zone or "", "cpuFr": float(cpu), "memFr": int(mem),
                "rttMs": float(self.rtt), "lcmUr": f"http://127.0.0.1:{self.port}/app_lcm/v2", "hstSt": "up"}

    def _heartbeat(self):
        while not self.stop.wait(1.0):
            try:
                self.c.update_fcnt(f"{self.name}/host", HOST_TP, self._attrs())
            except Exception:
                pass

    def _serve(self):
        agent = self

        class H(BaseHTTPRequestHandler):
            def _send(self, code, body=None):
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                code, body = agent.instantiate(req)
                self._send(code, body)

            def do_GET(self):
                iid = self.path.rstrip("/").rsplit("/", 1)[-1]
                inst = agent.instances.get(iid)
                self._send(200 if inst else 404, {"appInstanceId": iid, "instantiationState": "INSTANTIATED"} if inst else None)

            def do_DELETE(self):
                iid = self.path.rstrip("/").rsplit("/", 1)[-1]
                self._send(204 if agent.terminate(iid) else 404)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def instantiate(self, req):
        need = {"cpu": float(req.get("cpu", 0)), "mem": int(req.get("mem", 0))}
        cpu, mem = self.free()
        if need["cpu"] > cpu or need["mem"] > mem:
            return 409, {"detail": "insufficient resources"}
        iid = f"{req['appName'].replace('-', '')}{self.name.replace('-', '')}{next(self._ids)}"
        port = next(self.app_ports)
        try:
            if self.runtime == "docker":
                app = ContainerInstance(self.image, self.cse, req["appName"], iid, self.name, port, req["orchestrator"],
                                        need["cpu"], need["mem"]).start()
            else:
                app = app_class(req["appName"])(self.cse, req["appName"], iid, self.name, port, req["orchestrator"]).start()
        except Exception as e:
            return 500, {"detail": str(e)[:200]}
        self.instances[iid] = (app, need)
        return 201, {"appInstanceId": iid, "appAe": app.ae, "appOrigin": app.origin, "runtime": self.runtime,
                     "containerId": getattr(app, "container_id", None),
                     "_links": {"self": {"href": f"/app_lcm/v2/app_instances/{iid}"}}}

    def terminate(self, iid):
        inst = self.instances.pop(iid, None)
        if inst:
            inst[0].terminate()
            try:
                inst[0].c.delete(inst[0].ae)
            except Exception:
                pass
        return inst is not None

    def crash(self):
        """The host goes away: no heartbeat, no lifecycle API, its instances die with it."""
        self.stop.set()
        for app, _ in self.instances.values():
            app.terminate()
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()


# --- the orchestrator ------------------------------------------------------------------------------------
class Orchestrator:
    def __init__(self, cse: tuple, origin="SEGOrch", operators=(), heartbeat_timeout=2.5, log=print, bindings=None):
        """bindings: app name -> [{"path": device data container, "acp": its ACP (orchestrator is an owner)}]"""
        self.bindings = bindings or {}
        self.c = OneM2MClient(cse[0], cse[1], origin, timeout=2.0)
        self.origin, self.operators, self.hb_timeout, self.log = origin, list(operators), heartbeat_timeout, log
        self.intents: dict[str, dict] = {}            # name -> spec + runtime (host, instance, ...)
        self.events: list[dict] = []
        self.stop = threading.Event()

    def setup(self):
        c = self.c
        c.create_ae(ORCH_AE, api="Nedgeguard.orchestrator", lbl=["egs:orchestrator"])
        acp = c.create_acp(ORCH_AE, "acp_orch", [([self.origin], ALL_OPS),
                                                 (self.operators, RETRIEVE | DISCOVERY | CREATE, (28,))], [self.origin])
        c.request("PUT", ORCH_AE, None, {"m2m:ae": {"acpi": [acp["ri"]]}})
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def _ev(self, intent, step, **kw):
        e = {"t": time.time(), "intent": intent, "step": step, **kw}
        self.events.append(e)
        self.log(f"orchestrator: {intent}: {step} {kw if kw else ''}")

    # discover -> select
    def hosts(self):
        out = []
        for path in self.c.discover_label("egs:mec/host", ty=28):
            try:
                r = self.c.request("GET", path)[HOST_TP]
            except OneM2MError:
                continue
            r["_age"] = lt_age(r.get("lt", "19700101T000000"))
            r["_path"] = path
            out.append(r)
        return out

    def select(self, spec, exclude=()):
        cands = []
        for h in self.hosts():
            ok = (h.get("hstSt") == "up" and h["_age"] < self.hb_timeout and h["hstNm"] not in exclude
                  and h.get("cpuFr", 0) >= spec.get("cpuMn", 0) and h.get("memFr", 0) >= spec.get("memMn", 0)
                  and h.get("rttMs", 1e9) <= spec.get("maxLt", 1e9)
                  and (not spec.get("zone") or h.get("zone") in (spec["zone"], "")))
            if ok:
                same_zone = h.get("zone") == spec.get("zone")
                cands.append(((not same_zone, h["rttMs"], -h["cpuFr"]), h))
        cands.sort(key=lambda x: x[0])
        return [h for _, h in cands]

    # deploy -> register -> provision -> running
    def submit_check(self):
        """Pick up intents created by operators (children egs:depIn of the orchestrator AE)."""
        for path in self.c.discover(ORCH_AE, ty=28):
            rn = path.rsplit("/", 1)[-1]
            if rn in self.intents:
                continue
            spec = self.c.request("GET", path)[INTENT_TP]
            self.intents[rn] = {"spec": spec, "path": path, "status": "accepted", "host": None, "instance": None,
                                "excluded": set()}
            self._ev(rn, "accepted", app=spec.get("appNm"))
            threading.Thread(target=self.place, args=(rn,), daemon=True).start()

    def _set(self, rn, **attrs):
        self.intents[rn].update({k: v for k, v in attrs.items() if k in ("status",)})
        m = {"status": "intSt", "placement": "plcmt", "app_ae": "appAe"}
        try:
            self.c.update_fcnt(self.intents[rn]["path"], INTENT_TP, {m[k]: v for k, v in attrs.items() if k in m})
        except OneM2MError:
            pass

    def place(self, rn, reason="new"):
        it = self.intents[rn]
        spec = it["spec"]
        t0 = time.time()
        for h in self.select(spec, exclude=it["excluded"]):
            self._ev(rn, "selected", host=h["hstNm"], rtt=h["rttMs"], reason=reason)
            try:
                r = requests.post(f"{h['lcmUr']}/app_instances", timeout=3, json={
                    "appName": spec["appNm"], "appVersion": spec.get("appVr"), "cpu": spec.get("cpuMn", 0),
                    "mem": spec.get("memMn", 0), "orchestrator": self.origin})
            except requests.RequestException as e:
                self._ev(rn, "deploy_failed", host=h["hstNm"], error=str(e)[:80])
                continue
            if r.status_code != 201:
                self._ev(rn, "deploy_refused", host=h["hstNm"], code=r.status_code)
                continue
            inst = r.json()
            self._set(rn, status="deploying", placement=h["hstNm"])
            self._ev(rn, "deployed", host=h["hstNm"], instance=inst["appInstanceId"])
            if not self._wait_registered(inst["appAe"]):
                self._ev(rn, "register_timeout", host=h["hstNm"])
                continue
            self._ev(rn, "registered", app_ae=inst["appAe"])
            old = it.get("app_origin")
            self._provision(rn, inst, revoke=old, host=h)
            it.update(host=h["hstNm"], instance=inst["appInstanceId"], app_ae=inst["appAe"], app_origin=inst["appOrigin"],
                      lcm=h["lcmUr"], t_placed=time.time())
            if self._wait_running(inst["appAe"]):
                self._set(rn, status="running", placement=h["hstNm"], app_ae=inst["appAe"])
                self._ev(rn, "running", host=h["hstNm"], ms=round((time.time() - t0) * 1000, 1), reason=reason)
                return h["hstNm"]
        self._set(rn, status="unschedulable", placement="")
        self._ev(rn, "unschedulable", reason=reason)
        return None

    def _wait_registered(self, ae, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            try:                                 # registered = its config subscription exists (readable
                self.c.request("GET", f"{ae}/config/sub_self")   # only by the instance: 403 also means it exists)
                return True
            except OneM2MError as e:
                if e.status == 403:
                    return True
                time.sleep(0.05)
        return False

    def _wait_running(self, ae, timeout=6.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                self.c.request("GET", f"{ae}/status/la")
                return True
            except OneM2MError:
                time.sleep(0.1)
        return False

    def _provision(self, rn, inst, revoke=None, host=None):
        """Security context and configuration: the instance may read / subscribe to the device data of the
        intent (device ACPs list the orchestrator as an owner), then it is told what to subscribe to."""
        spec = self.intents[rn]["spec"]
        devices = self.bindings.get(spec["appNm"], [])
        acpis = []
        for d in devices:
            acp = self.c.request("GET", d["acp"])["m2m:acp"]
            rules = [r for r in acp["pv"]["acr"] if not (revoke and revoke in r["acor"])]
            rules.append({"acor": [inst["appOrigin"]], "acop": RETRIEVE | NOTIFY | CREATE, "acod": [{"chty": [23]}]})
            self.c.request("PUT", d["acp"], None, {"m2m:acp": {"pv": {"acr": rules}}})
            acpis.append(acp["ri"])
        self.c.create_cin(f"{inst['appAe']}/config", {"subscribe": [d["path"] for d in devices], "intent": rn,
                                                      "host": (host or {}).get("hstNm"), "zone": (host or {}).get("zone")})
        self._ev(rn, "provisioned", grants=len(devices), revoked=bool(revoke))

    # monitor
    def _loop(self):
        while not self.stop.wait(0.5):
            try:
                self.submit_check()
                alive = {h["hstNm"]: h["_age"] < self.hb_timeout and h.get("hstSt") == "up" for h in self.hosts()}
                for rn, it in list(self.intents.items()):
                    if it["status"] == "running" and not alive.get(it["host"], False):
                        self._ev(rn, "host_lost", host=it["host"])
                        it["excluded"].add(it["host"])
                        self._set(rn, status="migrating")
                        try:
                            self.c.delete(it["app_ae"])
                        except Exception:
                            pass
                        threading.Thread(target=self.place, args=(rn, "host_lost"), daemon=True).start()
            except Exception as e:
                self.log(f"orchestrator loop: {e}")


def submit_intent(c: OneM2MClient, name, app, zone=None, cpu=1.0, mem=256, max_latency=None, version="1.0"):
    """Operator side: one resource."""
    # governed by the orchestrator's ACP: the orchestrator manages the intent, operators read it
    attrs = {"appNm": app, "appVr": version, "cpuMn": float(cpu), "memMn": int(mem), "intSt": "submitted",
             "acpi": [f"{c.cse_rn}/{ORCH_AE}/acp_orch"]}
    if zone:
        attrs["zone"] = zone
    if max_latency is not None:
        attrs["maxLt"] = float(max_latency)
    return c.create_fcnt(ORCH_AE, INTENT_TP, f"intent_{name}", INTENT_CND, attrs, lbl=["egs:intent", f"egs:app/{app}"])
