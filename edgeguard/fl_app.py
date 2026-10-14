"""The federated-learning client as a deployable MEC application (app name "edgeguard-fl").

The orchestrator deploys it like any EdgeGuard instance (edgeguard/orchestration.py): an operator creates an
egs:depIn intent for the site's zone, a MEC host of that zone runs the instance (thread or container), the
instance registers its AE and is provisioned.  The provisioning tells it which site it serves; the instance
then

* loads that site's walking data from the host's local store (simulated: edgeguard/fl.py site_data),
* registers as an FL participant (AE fl_<site>, egs:flPrt, lbl egs:fl/participant) so the coordinator finds
  it by label, and refreshes the participant every second (liveness),
* trains when a round selects it and publishes only weights,
* follows the coordinator's model versions and evaluates each on the site's held-out data: inference at the
  edge, reported in its status heartbeat next to the constant-velocity baseline.

Raw trajectories never leave the instance; tools/fl_deploy_demo.py runs the whole lifecycle.
"""
from __future__ import annotations

import threading

from . import fl
from .onem2m import OneM2MClient
from .orchestration import EdgeApp

# local data store of each site's MEC host: seconds of walking data and seeds (the same split as tools/fl_demo.py)
SITE_DATA = {"seoul": (1200, 0), "busan": (1200, 1), "incheon": (240, 2), "daejeon": (600, 3)}


class FlEdgeApp(EdgeApp):
    def __init__(self, cse: tuple, name, instance, host, port, orchestrator):
        super().__init__(cse, name, instance, host, port, orchestrator)
        self.cse = cse
        self.client: fl.Client | None = None
        self.site = None
        self.test = None
        self.infer: dict = {}

    def on_provision(self, cfg):
        site = (cfg.get("zone") or "").lower()
        if site not in SITE_DATA or self.client is not None:
            return
        sec, seed = SITE_DATA[site]
        X, Y = fl.site_data(site, sec, seed=seed)
        self.test = fl.site_data(site, 600, seed=100 + seed)
        self.site = site
        url = f"http://127.0.0.1:{self.port}"
        self.client = fl.Client(OneM2MClient(self.cse[0], self.cse[1], f"Sfl{site}", timeout=3.0), site, X, Y,
                                f"{url}/round", log=lambda *a: None)
        self.client.register()
        self.client.c.create_subscription(f"{fl.COORD}/models", f"sub_infer_{site}", [f"{url}/model"])
        threading.Thread(target=self._liveness, daemon=True).start()

    def _liveness(self):
        while not self.stop.wait(1.0):
            try:
                self.client.c.update_fcnt(f"{self.client.ae}/participant", "egs:flPrt", {"avail": self.client.online})
            except Exception:
                pass

    def on_notify(self, path, con):
        if not isinstance(con, dict) or self.client is None:
            return
        if path == "/round":
            self.client.on_round(con)
        elif path == "/model" and "weights" in con:
            threading.Thread(target=self._evaluate, args=(con,), daemon=True).start()

    def _evaluate(self, m):
        """Inference at the edge: the new global model on this site's held-out data."""
        w = fl.unpack(m["weights"])
        ade = fl.ade(w, *self.test)
        if m["version"] >= self.infer.get("model_version", -1):
            self.infer = {"model_version": m["version"], "ade_2s": round(ade, 3),
                          "cv_2s": round(fl.ade(None, *self.test), 3)}

    def status_extra(self):
        if self.client is None:
            return {}
        self.processed = len(self.client.rounds_done)
        return {"fl": {"site": self.site, "rounds": list(self.client.rounds_done), **self.infer}}

    def terminate(self):
        if self.client is not None:
            self.client.online = False          # a dying host sends nothing more
        super().terminate()
