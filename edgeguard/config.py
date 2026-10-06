import os

import yaml

from .onem2m import OneM2MClient
from .risk import RiskConfig

DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "edgeguard.yaml")


def load(path=None):
    with open(path or os.environ.get("EDGEGUARD_CONFIG", DEFAULT)) as fh:
        return yaml.safe_load(fh)


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
    }
