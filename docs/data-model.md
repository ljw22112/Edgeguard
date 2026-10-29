# Data model: SDT flexContainers, labels, semantics

[← README](../README.md) · [한국어](ko/data-model.md)

Device state is modelled as **flexContainer specializations** from our own SDT domain (oneM2M TS-0023 style), instead of opaque JSON in contentInstances. Every resource is **labelled** for discovery and every device is **described semantically** with SAREF.

| | `data_model: sdt` (ACME, default for local demos) | `data_model: cin` (any CSE, incl. Mobius and the ESP32 firmware) |
|---|---|---|
| Position sample | UPDATE of `<dev>/tag\|module/kinematics` (egs:kinSt) | new contentInstance in `<dev>/location\|motion` |
| Device state | `cue` / `speedLimit` / `battery` modules | `<dev>/status` contentInstances |
| Discovery | labels + semantic query | device list in the config |

Both models run side by side (cameras and the firmware stay on contentInstances); the MEC app accepts both.

## The SDT domain `org.edgeguard.safety` (prefix `egs`)

File: [`config/onem2m/edgeguard.fcp`](../config/onem2m/edgeguard.fcp). `scripts/acme.sh` copies it next to ACME's own `.fcp` files at every start.

| Type | Kind | Attributes |
|---|---|---|
| `egs:wrkTg` workerTag | device class | zone; children kinematics, workerCue, `cod:bat` |
| `egs:frkMe` forkliftModule | device class | zone; children kinematics, speedLimit, `cod:bat` |
| `egs:kinSt` kinematicState | module class | positionX/Y, positionSigma, positionSource, speed, heading, yawRate, sampleTime |
| `egs:wrkCe` workerCue | module class | cueState (IDLE, WAIT, ASIDE, GO), cueSource |
| `egs:spdLt` speedLimit | module class | limit, maxSpeed; stopPointX / Y / Source (the stop point the module brakes for), plans (every plan it applies, `worker\|limit\|stop`: the MEC app re-sends a plan that is not reported), emergencyBrakeActive, reportTime |
| `cod:bat` battery | standard module class (org.onem2m.common) | level, charging, … |
| `egs:flTsk`, `egs:flPrt` | module classes | federated learning task and participant ([federated learning](federated-learning.md)) |

## Device twin

```
<dev> (AE, lbl egs:site/<site>, egs:role/<kind>, egs:id/<dev>)
  tag | module     egs:wrkTg | egs:frkMe        lbl … egs:device
    kinematics     egs:kinSt  fcied, mni 100   lbl … egs:module/kinematics     <- MEC app subscribes (net 1, update)
    cue | speedLimit                            what the device shows / enforces (written by the device)
    battery        cod:bat
    smd            semanticDescriptor, RDF/Turtle (dcrp 5), SAREF
  relay · status   containers (D2D relay, actuator confirmations)
  acp_<dev>        device: all · MEC app, MEC-IPE: retrieve, discover, notify, create subscriptions only
```

Built by `edgeguard/sdt.py: build_twin()`, used by setup, self-registration and CSE handover.

## Discovery: labels

- `GET /<cse>?fu=1&ty=28&lbl=egs:module/kinematics` returns every kinematics module.
- The MEC app runs this every 10 s (`discover_devices` in `mec_app/app.py`). A device that registered itself is subscribed to and tracked without being in any configuration. In a CI run it was onboarded in about 9 s.

## Semantics: SAREF

Each twin has a semantic descriptor:

```turtle
egs:forklift_01 a saref:Device , saref:Sensor , saref:Actuator , egs:ForkliftModule ;
    egs:role "forklift" ; egs:resource "forklift_01/module" ;
    saref:measuresProperty egs:Position , egs:Velocity ;
    saref:controlsProperty egs:DriveSpeed ;
    saref:consistsOf egs:DriveSpeedLimiter .
```

A semantic query (`fu=2&sqi=true&rcn=10&smf=<SPARQL>`) answers questions such as "forklifts that control their drive speed in zone A" and returns oneM2M paths: `edgeguard/sdt.py: query_devices()`, `OneM2MClient.semantic_query()`. ACME's semantic *resource discovery* (`sqi=false`) is refused by an argument check, so EdgeGuard uses the semantic query form.

## Access control

- ACPs with `accessControlObjectDetails` (`chty: [23]`) let the MEC app create **subscriptions only** in a device's twin. It cannot write data there.
- Another device's UPDATE is refused with 403 (checked by `deploy/check_sdt.py`).

## Check

```bash
scripts/acme.sh start in
EDGEGUARD_CONFIG=config/site.yaml EDGEGUARD_OVERRIDES=config/local-acme.yaml,config/live-demo.yaml scripts/run_live_demo.sh &
python deploy/check_sdt.py --onboard        # 6 checks, also in CI
```

The six checks: twins with labels, label discovery, kinematics history, semantic query, another device refused (ACP), and a self-registered device onboarded.
