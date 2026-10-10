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


# --- building a twin (setup, self-registration, CSE handover) --------------------------
def build_twin(dc, cfg, dev, kind, readers, zone=None, state=None, announce_to=None, log=print):
    """Create the device's AE and SDT twin on the CSE behind client `dc` (acting as the device),
    with its ACP: the device everything, `readers` (MEC app, MEC-IPE) create/read/discover/
    notify/delete, nobody else.  `state` ({rn: attrs}) restores module values (CSE handover);
    `announce_to` (CSE-IDs) announces the AE (oneM2M announcement: the IN-CSE then holds an
    AEAnnc whose lnk points at the serving CSE).  Returns the ACP resource."""
    from .onem2m import ALL_OPS, CREATE, RETRIEVE, DISCOVERY, NOTIFY
    rn, tp, cnd, act_rn, act_tp, act_cnd = DEVICE[kind]
    twin = twin_path(dev, kind)
    ae = {"m2m:ae": {"rn": dev, "api": f"Nedgeguard.{kind}", "rr": False, "srv": [dc.rvi],
                     "lbl": labels(cfg, dev, kind)[:3]}}
    if announce_to:
        ae["m2m:ae"].update(at=list(announce_to), aa=["lbl"])
    dc.with_retry(dc.request, "POST", "", 2, ae, ok_conflict=True)
    state = state or {}
    dc.with_retry(dc.create_fcnt, dev, tp, rn, cnd, {**({"zone": zone} if zone else {}), **state.get(rn, {})},
                  lbl=labels(cfg, dev, kind))
    kin = {"posX": 0.0, "posY": 0.0, "smpTe": 0, **state.get(KIN_RN, {})}
    dc.with_retry(dc.create_fcnt, twin, KIN_TP, KIN_RN, KIN_CND, kin, lbl=labels(cfg, dev, kind, "kinematics"), mni=100)
    init = {"cueSe": "IDLE"} if kind == "worker" else {"maxSd": float((cfg.get("forklift") or {}).get("max_speed", 2.5))}
    dc.with_retry(dc.create_fcnt, twin, act_tp, act_rn, act_cnd, {**init, **state.get(act_rn, {})},
                  lbl=labels(cfg, dev, kind, act_rn))
    dc.with_retry(dc.create_fcnt, twin, BAT_TP, "battery", BAT_CND, {"lvl": 100, **state.get("battery", {})},
                  lbl=labels(cfg, dev, kind, "battery"))
    dc.with_retry(dc.create_smd, twin, "smd", turtle_b64(saref_turtle(dev, kind, twin, zone)),
                  lbl=labels(cfg, dev, kind, "semantics"))
    me = dc.origin
    # readers (MEC app, MEC-IPE) read, discover and subscribe; their CREATE is limited to subscriptions
    # (accessControlObjectDetails chty 23), so no other entity can write into the twin
    rules = [([me], ALL_OPS), (list(readers), CREATE | RETRIEVE | DISCOVERY | NOTIFY, (23,))]
    acp = dc.with_retry(dc.create_acp, dev, f"acp_{dev}", rules, [me] + list(readers)[:1])
    for path, ptp in ((twin, tp), (f"{twin}/{KIN_RN}", KIN_TP), (f"{twin}/{act_rn}", act_tp),
                      (f"{twin}/battery", BAT_TP), (f"{twin}/smd", "m2m:smd")):
        dc.set_acpi(path, f"{dev}/acp_{dev}", acp.get("ri") if acp else None, tp=ptp)
    log(f"   {twin}: {tp} twin (kinematics, {act_rn}, battery, SAREF smd), ACP all = {me}, "
        f"read/subscribe = {', '.join(readers)}")
    return acp


TWIN_MODULES = {"worker": ("tag", KIN_RN, "cue", "battery"), "forklift": ("module", KIN_RN, "speedLimit", "battery")}
_SYSTEM = {"rn", "ri", "pi", "ty", "ct", "lt", "et", "st", "cs", "cnd", "lbl", "acpi", "at", "aa", "cr",
           "fcied", "mni", "mbs", "mia", "cni", "cbs", "or", "nl", "lnk"}


def read_state(c, dev, kind):
    """Module values of a twin ({rn: attrs}), for restoring it on another CSE."""
    twin = twin_path(dev, kind)
    out = {}
    for i, rn in enumerate(TWIN_MODULES[kind]):
        path = twin if i == 0 else f"{twin}/{rn}"
        res = c.request("GET", path) or {}
        for v in res.values():
            out[rn if i else DEVICE[kind][0]] = {k: x for k, x in v.items() if k not in _SYSTEM}
    return out
