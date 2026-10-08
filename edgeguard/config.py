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


def paths(cfg):
    """oneM2M resource paths relative to the CSE root."""
    ae = cfg["ae"]
    d = cfg["devices"]
    return {
        "ae": ae,
        "workers": {w: f"{ae}/{w}/location" for w in d.get("workers", [])},
        "forklifts": {f: f"{ae}/{f}/motion" for f in d.get("forklifts", [])},
        "cameras": {c: f"{ae}/{c}/detect" for c in d.get("cameras", [])},
        "risk": f"{ae}/risk",
        "alert": f"{ae}/alert",
        "control": f"{ae}/control",
        "nearmiss": f"{ae}/nearmiss",
    }
