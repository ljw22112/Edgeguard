import os

import yaml

from .onem2m import OneM2MClient
from .risk import RiskConfig

DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "edgeguard.yaml")


def merge(base, over):
    """Deep-merge `over` into a copy of `base` (dicts merge, everything else replaces)."""
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path=None):
    """Load the config; EDGEGUARD_OVERRIDES (a YAML file) is deep-merged on top, so a deployment
    (e.g. deploy/compose-overrides.yaml) changes only addresses and keeps the tuned site config."""
    with open(path or os.environ.get("EDGEGUARD_CONFIG", DEFAULT)) as fh:
        cfg = yaml.safe_load(fh)
    # comma-separated, applied in order; files that do not exist are skipped (optional layers,
    # e.g. deploy/sandbox/overrides.yaml only exists while connected to an ETSI MEC Sandbox)
    for over in filter(None, (os.environ.get("EDGEGUARD_OVERRIDES") or "").split(",")):
        if os.path.exists(over.strip()):
            with open(over.strip()) as fh:
                cfg = merge(cfg, yaml.safe_load(fh) or {})
    return cfg


def client(cfg):
    c = cfg["cse"]
    return OneM2MClient(c["base_url"], c["cse_rn"], c["origin"], str(c.get("rvi", "3")))


def risk_config(cfg):
    return RiskConfig(**cfg.get("risk", {}))


def device_origin(cfg, dev):
    """oneM2M originator of a device's own AE (security.originators, else S<id> without '_')."""
    o = ((cfg.get("security") or {}).get("originators") or {}).get(dev)
    return o or "S" + dev.replace("_", "")


def device_client(cfg, dev):
    """Client acting as the device itself (its AE owns its containers)."""
    c = cfg["cse"]
    return OneM2MClient(c["base_url"], c["cse_rn"], device_origin(cfg, dev), str(c.get("rvi", "3")))


def paths(cfg):
    """oneM2M resource paths relative to the CSE root.

    layout "device_ae" (default): every device registers its own AE (originator = the device) with
    its data container under it - <CSE>/worker_01/location - and the MEC app's AE holds what the
    MEC app writes - <CSE>/EdgeGuard/{risk, alert, control, nearmiss, mec_lease}.
    layout "single_ae" (v1.2 and earlier): device containers under the MEC app's AE."""
    ae = cfg["ae"]
    d = cfg["devices"]
    root = "" if cfg.get("layout", "device_ae") == "device_ae" else f"{ae}/"
    leaf = {"workers": "location", "forklifts": "motion", "cameras": "detect"}
    out = {"ae": ae, "layout": "device_ae" if not root else "single_ae"}
    for group, cnt in leaf.items():
        out[group] = {dev: f"{root}{dev}/{cnt}" for dev in d.get(group, [])}
    out["device_ae"] = {dev: f"{root}{dev}" for g in leaf for dev in d.get(g, [])}
    # D2D relay: a tag / forklift module posts positions it heard from a neighbour in a radio shadow
    # into its OWN AE (<dev>/relay), so no device ever writes into another device's AE
    out["relay"] = ({dev: f"{dev}/relay" for g in ("workers", "forklifts") for dev in d.get(g, [])}
                    if not root else {})
    # actuator confirmations from real boards (firmware postAck): <dev>/status
    out["status"] = {dev: f"{dev}/status" for g in ("workers", "forklifts") for dev in d.get(g, [])} if not root else {}
    out.update({k: f"{ae}/{k}" for k in ("risk", "alert", "control", "nearmiss", "mec_lease")})
    return out
