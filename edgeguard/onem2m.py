"""Minimal oneM2M HTTP-binding client (Mca), tested against ACME CSE and
written to the same API that KETI Mobius serves.

Resource types used: AE (ty=2), container (ty=3), contentInstance (ty=4),
subscription (ty=23).
"""
from __future__ import annotations

import itertools
import json
import time

import requests

TY_AE, TY_CNT, TY_CIN, TY_SUB = 2, 3, 4, 23
_ri = itertools.count(1)


class OneM2MError(RuntimeError):
    def __init__(self, status, rsc, body, path):
        super().__init__(f"oneM2M {status} rsc={rsc} on {path}: {body}")
        self.status, self.rsc = status, rsc


class OneM2MClient:
    """`base_url` is the CSE's HTTP root (e.g. http://localhost:8080),
    `cse_rn` its resource name (`cse-in` for ACME, `Mobius` for Mobius)."""

    def __init__(self, base_url, cse_rn, origin, rvi="3", timeout=3.0):
        self.base = base_url.rstrip("/")
        self.cse_rn = cse_rn
        self.origin = origin
        self.rvi = rvi
        self.timeout = timeout
        self.s = requests.Session()

    # --- low level -------------------------------------------------------
    def url(self, path=""):
        path = path.strip("/")
        return f"{self.base}/{self.cse_rn}" + (f"/{path}" if path else "")

    def request(self, method, path, ty=None, body=None, ok_conflict=False):
        h = {"X-M2M-Origin": self.origin, "X-M2M-RI": f"eg{next(_ri)}",
             "X-M2M-RVI": self.rvi, "Accept": "application/json"}
        if body is not None:
            h["Content-Type"] = "application/json" + (f";ty={ty}" if ty else "")
        r = self.s.request(method, self.url(path), headers=h,
                           data=None if body is None else json.dumps(body),
                           timeout=self.timeout)
        rsc = r.headers.get("X-M2M-RSC")
        if r.status_code == 409 and ok_conflict:
            return None
        if r.status_code >= 400:
            raise OneM2MError(r.status_code, rsc, r.text[:300], path)
        return r.json() if r.content else None

    # --- resources ---------------------------------------------------------
    def create_ae(self, rn, api="Nedgeguard", poa=None):
        body = {"m2m:ae": {"rn": rn, "api": api, "rr": bool(poa), "srv": [self.rvi]}}
        if poa:
            body["m2m:ae"]["poa"] = poa
        return self.request("POST", "", TY_AE, body, ok_conflict=True)

    def create_container(self, parent, rn, mni=200):
        body = {"m2m:cnt": {"rn": rn, "mni": mni}}
        return self.request("POST", parent, TY_CNT, body, ok_conflict=True)

    def create_cin(self, parent, con):
        return self.request("POST", parent, TY_CIN, {"m2m:cin": {"con": con}})

    def create_subscription(self, parent, rn, nu, net=(3,)):
        """net 3 = 'create of a direct child resource' (a new contentInstance).
        If the subscription already exists its notification URIs are updated."""
        body = {"m2m:sub": {"rn": rn, "nu": list(nu), "nct": 1,
                            "enc": {"net": list(net)}}}
        res = self.request("POST", parent, TY_SUB, body, ok_conflict=True)
        if res is None:
            res = self.request("PUT", f"{parent}/{rn}", None, {"m2m:sub": {"nu": list(nu)}})
        return res

    def with_retry(self, fn, *args, attempts=6, wait=0.3):
        """Retry on 404: some CSEs (Mobius cluster mode) make a new parent visible
        to other workers only after a short delay."""
        for i in range(attempts):
            try:
                return fn(*args)
            except OneM2MError as e:
                if e.status != 404 or i == attempts - 1:
                    raise
                time.sleep(wait)

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
    ("cin", payload) for a new contentInstance, or (None, None)."""
    sgn = body.get("m2m:sgn", body)
    if sgn.get("vrq"):
        return "verify", None
    rep = (sgn.get("nev") or {}).get("rep") or {}
    cin = rep.get("m2m:cin")
    if cin is not None:
        return "cin", decode_con(cin.get("con"))
    return None, None


def now_ms():
    return int(time.time() * 1000)
