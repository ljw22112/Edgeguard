"""Minimal oneM2M HTTP-binding client (Mca), tested against ACME CSE and
written to the same API that KETI Mobius serves.

Resource types used: AE (ty=2), container (ty=3), contentInstance (ty=4),
subscription (ty=23), semanticDescriptor (ty=24), flexContainer (ty=28, SDT specializations
from config/onem2m/edgeguard.fcp - see edgeguard/sdt.py).
"""
from __future__ import annotations

import itertools
import json
import time

import requests

TY_ACP, TY_AE, TY_CNT, TY_CIN, TY_SUB, TY_SMD, TY_FCNT = 1, 2, 3, 4, 23, 24, 28
CREATE, RETRIEVE, UPDATE, DELETE, NOTIFY, DISCOVERY = 1, 2, 4, 8, 16, 32
ALL_OPS = 63
_ri = itertools.count(1)


class OneM2MError(RuntimeError):
    def __init__(self, status, rsc, body, path):
        super().__init__(f"oneM2M {status} rsc={rsc} on {path}: {body}")
        self.status, self.rsc = status, rsc


class OneM2MClient:
    """`base_url` is the CSE's HTTP root (e.g. http://localhost:8080),
    `cse_rn` its resource name (`cse-in` for ACME, `Mobius` for Mobius)."""

    def __init__(self, base_url, cse_rn, origin, rvi="3", timeout=3.0, verify=None):
        self.base = base_url.rstrip("/")
        self.cse_rn = cse_rn
        self.origin = origin
        self.rvi = rvi
        self.timeout = timeout
        self.s = requests.Session()
        self.verify = verify            # HTTPS: CA bundle of the site PKI (docs/transport-security.md)

    # --- low level -------------------------------------------------------
    def url(self, path=""):
        path = path.strip("/")
        return f"{self.base}/{self.cse_rn}" + (f"/{path}" if path else "")

    def request(self, method, path, ty=None, body=None, ok_conflict=False, params=None):
        h = {"X-M2M-Origin": self.origin, "X-M2M-RI": f"eg{next(_ri)}",
             "X-M2M-RVI": self.rvi, "Accept": "application/json"}
        if body is not None:
            h["Content-Type"] = "application/json" + (f";ty={ty}" if ty else "")
        kw = {} if self.verify is None else {"verify": self.verify}   # per request: env CA bundles win over Session.verify
        r = self.s.request(method, self.url(path), headers=h, params=params, **kw,
                           data=None if body is None else json.dumps(body),
                           timeout=self.timeout)
        rsc = r.headers.get("X-M2M-RSC")
        if r.status_code == 409 and ok_conflict:
            return None
        if r.status_code >= 400:
            raise OneM2MError(r.status_code, rsc, r.text[:300], path)
        return r.json() if r.content else None

    # --- resources ---------------------------------------------------------
    def create_ae(self, rn, api="Nedgeguard", poa=None, lbl=None):
        body = {"m2m:ae": {"rn": rn, "api": api, "rr": bool(poa), "srv": [self.rvi]}}
        if poa:
            body["m2m:ae"]["poa"] = poa
        if lbl:
            body["m2m:ae"]["lbl"] = list(lbl)
        return self.request("POST", "", TY_AE, body, ok_conflict=True)

    def create_container(self, parent, rn, mni=200):
        body = {"m2m:cnt": {"rn": rn, "mni": mni}}
        return self.request("POST", parent, TY_CNT, body, ok_conflict=True)

    def create_cin(self, parent, con):
        return self.request("POST", parent, TY_CIN, {"m2m:cin": {"con": con}})

    def publish(self, path, con):
        """A device sample: an UPDATE of its kinematics flexContainer (SDT data model) or a new
        contentInstance in its data container (cin data model), depending on the path."""
        if path.rstrip("/").endswith("/kinematics"):
            from .sdt import KIN_TP, to_kin
            return self.update_fcnt(path, KIN_TP, to_kin(con))
        return self.create_cin(path, con)

    def create_subscription(self, parent, rn, nu, net=None, acpi=None):
        """net 3 = 'create of a direct child resource' (a new contentInstance); for a flexContainer
        kinematics module (SDT data model) the default is net 1 = 'update of the resource'.
        If the subscription already exists its notification URIs are updated."""
        if net is None:
            net = (1,) if parent.rstrip("/").endswith("/kinematics") else (3,)
        body = {"m2m:sub": {"rn": rn, "nu": list(nu), "nct": 1,
                            "enc": {"net": list(net)}}}
        if acpi:      # e.g. the device's ACP: the device may read the subscription and carry it to
            body["m2m:sub"]["acpi"] = list(acpi)   # another CSE on handover (edgeguard/handover.py)
        res = self.request("POST", parent, TY_SUB, body, ok_conflict=True)
        if res is None:
            res = self.request("PUT", f"{parent}/{rn}", None, {"m2m:sub": {"nu": list(nu)}})
        return res

    # --- SDT data model: flexContainer, semanticDescriptor, discovery ---------
    def create_fcnt(self, parent, tp, rn, cnd, attrs=None, lbl=None, mni=None):
        """flexContainer specialization `tp` (e.g. egs:kinSt).  mni > 0 keeps that many
        flexContainerInstances (history of the module's states)."""
        body = {"rn": rn, "cnd": cnd, **(attrs or {})}
        if lbl:
            body["lbl"] = list(lbl)
        if mni:
            body.update(fcied=True, mni=mni)
        return self.request("POST", parent, TY_FCNT, {tp: body}, ok_conflict=True)

    def update_fcnt(self, path, tp, attrs):
        return self.request("PUT", path, None, {tp: dict(attrs)})

    def create_smd(self, parent, rn, turtle_b64, lbl=None):
        """semanticDescriptor in RDF/Turtle (dcrp 5)."""
        body = {"m2m:smd": {"rn": rn, "dcrp": 5, "dsp": turtle_b64, **({"lbl": list(lbl)} if lbl else {})}}
        res = self.request("POST", parent, TY_SMD, body, ok_conflict=True)
        if res is None:
            res = self.request("PUT", f"{parent}/{rn}", None, {"m2m:smd": {"dsp": turtle_b64}})
        return res

    def discover_label(self, label, parent="", ty=None):
        """Paths of the resources carrying `label` (oneM2M discovery, filter criteria lbl)."""
        params = {"fu": 1, "lbl": label}
        if ty:
            params["ty"] = ty
        res = self.request("GET", parent, params=params) or {}
        return [self._rel(u) for u in res.get("m2m:uril") or []]

    def semantic_query(self, sparql, parent=""):
        """Semantic query (sqi=true, rcn=semanticContent) over the semanticDescriptors below
        `parent`; returns the SPARQL JSON result bindings as plain dicts."""
        res = self.request("GET", parent, params={"fu": 2, "smf": sparql, "sqi": "true", "rcn": 10}) or {}
        q = res.get("m2m:qres")
        q = json.loads(q) if isinstance(q, str) else (q or {})
        return [{k: v.get("value") for k, v in b.items()} for b in q.get("results", {}).get("bindings", [])]

    def _rel(self, u):
        u = u.strip("/")
        if u.startswith(self.cse_rn + "/"):
            return u[len(self.cse_rn) + 1:]
        if "/" + self.cse_rn + "/" in "/" + u:
            return u.split(self.cse_rn + "/", 1)[1]
        return u

    def with_retry(self, fn, *args, attempts=6, wait=0.3, **kw):
        """Retry on 404: some CSEs (Mobius cluster mode) make a new parent visible
        to other workers only after a short delay."""
        for i in range(attempts):
            try:
                return fn(*args, **kw)
            except OneM2MError as e:
                if e.status != 404 or i == attempts - 1:
                    raise
                time.sleep(wait)

    def create_acp(self, parent, rn, rules, owners):
        """rules: [(originators, ops)] or [(originators, ops, child types)] - the third element limits
        CREATE to those child resource types (accessControlObjectDetails chty), e.g. (23,) = may
        create subscriptions but no data; owners may change the ACP itself."""
        def acr(rule):
            o, op = rule[0], rule[1]
            e = {"acor": list(o), "acop": op}
            if len(rule) > 2 and rule[2]:
                e["acod"] = [{"chty": list(rule[2])}]
            return e
        body = {"m2m:acp": {"rn": rn,
                            "pv": {"acr": [acr(r) for r in rules]},
                            "pvs": {"acr": [{"acor": list(owners), "acop": ALL_OPS}]}}}
        res = self.request("POST", parent, TY_ACP, body, ok_conflict=True)
        if res is None:                                  # exists: refresh its rules
            res = self.request("PUT", f"{parent}/{rn}", None,
                               {"m2m:acp": {"pv": body["m2m:acp"]["pv"]}})
        return res["m2m:acp"]

    def set_acpi(self, path, acp_path, acp_ri=None, tp="m2m:cnt"):
        """Attach an ACP; structured path works on Mobius, resource id is the fallback.
        tp: the resource's type key (m2m:cnt, or a flexContainer specialization such as egs:kinSt)."""
        last = None
        for ref in [f"{self.cse_rn}/{acp_path}"] + ([acp_ri] if acp_ri else []):
            try:
                return self.request("PUT", path, None, {tp: {"acpi": [ref]}})
            except OneM2MError as e:
                last = e
        raise last

    def discover(self, parent, ty=TY_CNT):
        """Paths (relative to the CSE root) of all resources of type `ty` below `parent`."""
        res = self.request("GET", parent, params={"fu": 1, "ty": ty}) or {}
        out = []
        for u in res.get("m2m:uril") or []:
            u = u.strip("/")
            if u.startswith(self.cse_rn + "/"):
                u = u[len(self.cse_rn) + 1:]
            elif "/" + self.cse_rn + "/" in "/" + u:            # SP-relative form /cseId/cseRn/...
                u = u.split(self.cse_rn + "/", 1)[1]
            out.append(u)
        return out

    def latest(self, container):
        res = self.request("GET", f"{container}/la")
        return decode_con(res["m2m:cin"]["con"])

    def delete(self, path):
        try:
            return self.request("DELETE", path)
        except OneM2MError as e:
            if e.status != 404:
                raise


def decode_con(con):
    if isinstance(con, str):
        try:
            return json.loads(con)
        except ValueError:
            return con
    return con


def parse_notification(body: dict):
    """Return ("verify", None) for a subscription verification request,
    ("cin", payload) for a new contentInstance, ("fcnt", {"tp": type, **attributes}) for an
    updated flexContainer (SDT data model), or (None, None)."""
    sgn = body.get("m2m:sgn", body)
    if sgn.get("vrq"):
        return "verify", None
    rep = (sgn.get("nev") or {}).get("rep") or {}
    cin = rep.get("m2m:cin")
    if cin is not None:
        return "cin", decode_con(cin.get("con"))
    for tp, res in rep.items():
        if not tp.startswith("m2m:") and isinstance(res, dict) and "cnd" in res:
            return "fcnt", {"tp": tp, **res}
    return None, None


def now_ms():
    return int(time.time() * 1000)
