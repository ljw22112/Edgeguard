# Tutorial: a oneM2M safety app in 10 minutes

[← README](../README.md) · [한국어](ko/tutorial-onem2m.md)

This tutorial builds the core of EdgeGuard with nothing but HTTP requests to a oneM2M CSE: a worker tag publishes its position, a safety app finds it, subscribes, and writes an alert into the tag's inbox when the worker walks into the forklift aisle. The full script is [`tools/tutorial_safety_app.py`](../tools/tutorial_safety_app.py), about 100 lines with `requests` only; CI runs it on every commit.

```bash
scripts/acme.sh start in                 # ACME CSE on :8080 (or set CSE / CSE_RN for Mobius or another CSE)
python tools/tutorial_safety_app.py      # prints every request and 5 PASS lines
```

## Every request carries three headers

oneM2M over HTTP (TS-0009) puts the originator, a request ID and the release version in headers. The resource type of a CREATE goes in the content type.

```
POST /cse-in              X-M2M-Origin: CTutorialTag   X-M2M-RI: 8f3a…   X-M2M-RVI: 3
Content-Type: application/json;ty=2
```

## 1. The tag registers and creates its containers

```json
POST /cse-in  ty=2   {"m2m:ae": {"rn": "tutorial_tag", "api": "Ntutorial.tag", "rr": false, "srv": ["3"],
                                 "lbl": ["tutorial/worker-tag", "zone/A"]}}
POST /cse-in/tutorial_tag  ty=3   {"m2m:cnt": {"rn": "position", "mni": 50}}
POST /cse-in/tutorial_tag  ty=3   {"m2m:cnt": {"rn": "alerts", "mni": 20}}
```

`rr: false` says the tag cannot be reached from outside: it sits behind NAT. `mni` keeps history bounded. The labels are how applications find it later, without a device list.

## 2. The tag decides who may do what

Three access control policies (TS-0003). Each `acr` rule lists originators and an operation bit mask: CREATE 1, RETRIEVE 2, UPDATE 4, DELETE 8, NOTIFY 16, DISCOVERY 32.

| ACP | On | The app may |
|---|---|---|
| `acp_ae` | the AE | RETRIEVE + DISCOVERY: find the tag |
| `acp_tag` | `position` | RETRIEVE, DISCOVERY, NOTIFY, and CREATE limited to subscriptions (`acod.chty = [23]`) |
| `acp_alerts` | `alerts` | CREATE limited to contentInstances (`chty = [4]`), not even read them |

```json
POST /cse-in/tutorial_tag  ty=1
{"m2m:acp": {"rn": "acp_tag",
  "pv":  {"acr": [{"acor": ["CTutorialTag"], "acop": 63},
                  {"acor": ["CTutorialApp"], "acop": 51, "acod": [{"chty": [23]}]}]},
  "pvs": {"acr": [{"acor": ["CTutorialTag"], "acop": 63}]}}}
PUT  /cse-in/tutorial_tag/position   {"m2m:cnt": {"acpi": ["<ri of acp_tag>"]}}
```

## 3. The app registers and discovers tags by label

```
POST /cse-in  ty=2   {"m2m:ae": {"rn": "tutorial_app", "rr": true, "poa": ["http://127.0.0.1:9399"], …}}
GET  /cse-in?fu=1&lbl=tutorial/worker-tag&ty=2        →  {"m2m:uril": ["cse-in/tutorial_tag"]}
```

`poa` is where the CSE delivers notifications. Discovery returns only what the app is allowed to see.

## 4. Subscribe

```json
POST /cse-in/tutorial_tag/position  ty=23
{"m2m:sub": {"rn": "sub_app", "nu": ["cse-in/tutorial_app"], "enc": {"net": [3]}}}
```

`nu` names the app's AE; the CSE resolves it to the `poa`. Before accepting, the CSE sends a verification request (`vrq: true`) and the app answers 2000. `net: 3` means "notify me about new child resources".

## 5. Publish, notify, decide, alert

```
POST /cse-in/tutorial_tag/position  ty=4   {"m2m:cin": {"con": {"x": 31.0, "y": 12.5}}}
   → CSE notifies the app:  {"m2m:sgn": {"nev": {"rep": {"m2m:cin": {"con": {"x": 31.0, "y": 12.5}}}, "net": 3}, "sur": "…/sub_app"}}
   → app: y inside the aisle (7–13 m)
POST /cse-in/tutorial_tag/alerts  ty=4  (CTutorialApp)   {"m2m:cin": {"con": {"cue": "WAIT"}}}
```

The tag and the app never talk to each other directly. Any other application with the right ACP could subscribe to the same position, which is how EdgeGuard adds a dashboard, an AI agent and federated learning without touching the devices.

## 6. Access control in action

```
GET  /cse-in/tutorial_tag/alerts/la   (CTutorialTag)  → 200 {"cue": "WAIT", …}
POST /cse-in/tutorial_tag/alerts      (CStranger)     → 403
GET  /cse-in/tutorial_tag/alerts/la   (CTutorialApp)  → 403   the app may create alerts, not read them
```

## Where EdgeGuard goes further

| Step in this tutorial | EdgeGuard | oneM2M spec | Code |
|---|---|---|---|
| position as contentInstance | SDT flexContainer twins with SAREF semantics | TS-0023, TS-0034 | [data-model.md](data-model.md) |
| one alert to one tag | one request to a zone `<group>`'s fanOutPoint reaches every tag in the zone | TS-0001 §9.6.13 | [zones.py](../edgeguard/zones.py) |
| `rr: false` | tags receive through a `<pollingChannel>` | TS-0001 §9.6.21 | [transport-security.md](transport-security.md) |
| HTTP | devices on the MQTT binding over mutual TLS, apps on HTTPS | TS-0010, TS-0009 | [mqtt_binding.py](../edgeguard/mqtt_binding.py) |
| one CSE | zone MN-CSEs under an IN-CSE; a forklift's AE moves between them with announcement | TS-0001 §9.6.26, TR-0077 §7.2 | [handover.md](handover.md) |
| fixed aisle rule | collision-course prediction on an ETSI MEC host, positions from MEC 013 through the MEC-IPE | TR-0077 §7.1 | [mobility.md](mobility.md), [mec-platform.md](mec-platform.md) |
| one app | apps deployed by an orchestrator from one intent resource; FL clients the same way | TR-0077 §7.1, §7.3, TR-0084 | [orchestration.md](orchestration.md) |
