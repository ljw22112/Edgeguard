"""EdgeGuard SDT data model (oneM2M TS-0023 style flexContainers, config/onem2m/edgeguard.fcp).

data_model "sdt" (cfg onem2m.data_model): every worker tag / forklift module keeps a device twin
under its own AE, built from flexContainer specializations, labelled for discovery and described
semantically with SAREF:

  <dev> (AE, lbl egs:role/<kind>)
    tag | module          egs:wrkTg / egs:frkMe     device class, attribute zone
      kinematics          egs:kinSt (mni 100)       one UPDATE per position sample -> subscribers
      cue | speedLimit    egs:wrkCe / egs:spdLt     what the device shows / enforces
      battery             cod:bat                   standard module class (org.onem2m.common)
      smd                 semanticDescriptor        SAREF description (RDF/Turtle)

Labels: egs:site/<site>, egs:role/<worker|forklift>, egs:id/<dev>, egs:module/<name>.  The MEC app
finds every kinematics module with one discovery request (lbl=egs:module/kinematics) and so onboards
devices that registered themselves, without a device list.  data_model "cin" (default, any CSE incl.
Mobius) keeps the plain <dev>/location | motion containers.
"""
from __future__ import annotations

import base64

NS = "https://edgeguard.example/ns#"
SAREF = "https://saref.etsi.org/core/"
DOMAIN = "org.edgeguard.safety"

DEVICE = {   # kind -> (twin rn, type, cnd, actuator module rn, type, cnd)
    "worker": ("tag", "egs:wrkTg", f"{DOMAIN}.device.workerTag",
               "cue", "egs:wrkCe", f"{DOMAIN}.moduleclass.workerCue"),
    "forklift": ("module", "egs:frkMe", f"{DOMAIN}.device.forkliftModule",
                 "speedLimit", "egs:spdLt", f"{DOMAIN}.moduleclass.speedLimit"),
}
KIN_TP, KIN_CND = "egs:kinSt", f"{DOMAIN}.moduleclass.kinematicState"
BAT_TP, BAT_CND = "cod:bat", "org.onem2m.common.moduleclass.battery"
KIN_RN = "kinematics"
KIND_OF = {"workers": "worker", "forklifts": "forklift"}


def model(cfg) -> str:
    return ((cfg.get("onem2m") or {}).get("data_model") or "cin").lower()


def twin_path(dev, kind):
    return f"{dev}/{DEVICE[kind][0]}"


def kin_path(dev, kind):
    return f"{twin_path(dev, kind)}/{KIN_RN}"


def is_kin(path: str) -> bool:
    return path.rstrip("/").endswith("/" + KIN_RN)


def labels(cfg, dev, kind, module=None):
    site = (cfg.get("site") or {}).get("name", "site-1") if isinstance(cfg.get("site"), dict) else "site-1"
    out = [f"egs:site/{site}", f"egs:role/{kind}", f"egs:id/{dev}"]
    return out + ([f"egs:module/{module}"] if module else ["egs:device"])


def from_label(lbl, key):
    for v in lbl or []:
        if isinstance(v, str) and v.startswith(f"egs:{key}/"):
            return v.split("/", 1)[1]
    return None


# --- samples <-> kinematicState ---------------------------------------------
_FIELDS = (("x", "posX"), ("y", "posY"), ("pos_sigma", "posSa"), ("source", "posSe"),
           ("speed", "speed"), ("heading", "headg"), ("yaw_rate", "yawRe"), ("ts", "smpTe"))


def to_kin(sample: dict) -> dict:
    """EdgeGuard sample dict -> egs:kinSt attributes (only the ones present)."""
    out = {}
    for k, a in _FIELDS:
        v = sample.get(k)
        if v is not None:
            out[a] = int(v) if a == "smpTe" else v
    return out


def from_kin(attrs: dict, lbl=None) -> dict:
    """egs:kinSt representation (as notified) -> EdgeGuard sample dict."""
    s = {k: attrs[a] for k, a in _FIELDS if attrs.get(a) is not None}
    s["id"] = from_label(lbl if lbl is not None else attrs.get("lbl"), "id")
    s["kind"] = from_label(lbl if lbl is not None else attrs.get("lbl"), "role")
    return s


# --- semantics ----------------------------------------------------------------
def saref_turtle(dev, kind, path, zone=None):
    """SAREF description of a device twin; egs:resource ties the RDF node to the oneM2M path so a
    semantic query answers with resources an application can subscribe to."""
    node = f"egs:{dev}"
    actuator = "egs:VibrationMotor" if kind == "worker" else "egs:DriveSpeedLimiter"
    cls = "egs:WorkerTag" if kind == "worker" else "egs:ForkliftModule"
    lines = [
        f"@prefix saref: <{SAREF}> .",
        f"@prefix egs: <{NS}> .",
        f"{node} a saref:Device , saref:Sensor , saref:Actuator , {cls} ;",
        f'    egs:role "{kind}" ;',
        f'    egs:resource "{path}" ;',
        "    saref:measuresProperty egs:Position , egs:Velocity ;",
        "    saref:controlsProperty egs:WorkerCue ;" if kind == "worker" else "    saref:controlsProperty egs:DriveSpeed ;",
        f"    saref:consistsOf {actuator} ;",
        "    saref:hasFunction saref:SensingFunction , saref:ActuatingFunction"
        + (f' ;\n    egs:zone "{zone}" .' if zone else " ."),
    ]
    return "\n".join(lines)


def turtle_b64(ttl: str) -> str:
    return base64.b64encode(ttl.encode()).decode()


def query_devices(role=None, zone=None, actuates=None):
    """SPARQL over the SAREF descriptions: devices (and their oneM2M paths) by role / zone / what
    they actuate."""
    where = ["?d a saref:Device ; egs:resource ?path ; egs:role ?role ."]
    if role:
        where.append(f'?d egs:role "{role}" .')
    if zone:
        where.append(f'?d egs:zone "{zone}" .')
    if actuates:
        where.append(f"?d saref:controlsProperty egs:{actuates} .")
    return (f"PREFIX saref: <{SAREF}> PREFIX egs: <{NS}> "
            f"SELECT ?d ?path ?role WHERE {{ {' '.join(where)} }}")
