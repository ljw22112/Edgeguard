# Deployment

Docker Compose stack, local demo, deployment architecture decision (measured), oneM2M resource tree, firmware and CI.

[← README](../README.md) · [한국어](ko/deployment.md)

## MEC host deployment (Docker Compose)

Brings up MariaDB + Mobius (oneM2M IN-CSE) + the MEC app in one go. Alert policy, adaptive reporting rates and access control come straight from `config/site.yaml`;
only addresses are overridden by `deploy/compose-overrides.yaml` (`EDGEGUARD_OVERRIDES`, deep merge).

```bash
cd deploy
docker compose up -d                    # MEC host stack (includes build)
docker compose --profile demo up        # + oneM2M resource setup + virtual devices (4 encounters)
python3 check_demo.py out/devices.json http://localhost:9090/health
# Dashboard at http://localhost:9090/ · physical devices connect to http://<host>:7579/Mobius
```

Prebuilt images (the repository is private, so log in with a token: a PAT with `read:packages` scope):
```bash
echo $GHCR_TOKEN | docker login ghcr.io -u <GitHub username> --password-stdin
export EDGEGUARD_IMAGE_TAG=latest EDGEGUARD_PULL_POLICY=always   # Windows cmd: set each with `set`
docker compose up -d
```

| Component | Image | Notes |
|---|---|---|
| MariaDB | `mariadb:11.4` | Data in the `db-data` volume |
| Mobius | `ghcr.io/ljw22112/edgeguard-mobius` | Pinned commit + locked dependencies. On start: writes `conf.json`, seals it, imports the schema once |
| MEC app | `ghcr.io/ljw22112/edgeguard-mec` | Runs as non-root, `/health` health check. The same image runs setup and the virtual devices |

- Mobius connects to the DB at a hard-coded `localhost:3306`, so it shares the MariaDB container's network; other services reach it via the alias `mobius`.
- `.github/workflows/docker.yml`: on every push, build from official base images → start the stack → verify alerts for the 4 demo encounters
  (`deploy/check_demo.py`: all 4 alerted at least 1 s ahead, 0 write failures) → restart with the DB kept and verify again → on main, publish to GHCR
  (`latest`, `sha-<commit>`).
- Test results (this environment, 4 encounters × 3 runs): lead time 3.6–3.9 s, median alert latency 25–31 ms, 0 write failures.
- Measured on a team laptop (Galaxy Book2 Pro · 8 GB RAM, Windows 11 + Docker Desktop/WSL2, `results/deploy_windows_pc.json`): all 4 encounters alerted, lead times 3.83 / 3.54 / 3.62 / 3.51 s,
  median alert latency 58 ms (p95 82 ms), 30 alerts, 0 write failures.
- Deployment testing found and fixed one bug: if tracking dropped between encounters, the pair's alert state stayed at WARNING,
  so the first alert of the next encounter went out as a "refresh", which may not trigger vibration. Now a pair not evaluated for 2 s or more starts as a new encounter
  (repeat-run lead times 1.1 / 0.8 / 3.7 / 1.3 s → 3.9 / 3.6 / 3.7 / 3.6 s).

## Local demo (no hardware)

```bash
pip install -r requirements.txt
scripts/run_local_demo.sh crossing_conflict
```
Downloads and runs ACME CSE (open-source oneM2M), starts the MEC app and virtual devices, then creates the resources.
Scenarios: `crossing_conflict crossing_clear head_on adjacent_aisle roadside_picker turn_into_worker turn_away worker_yields`

Running locally, the median from sensor sample → CSE → MEC → CSE → device alert was about 25–35 ms
(measured within a single PC, excluding real network latency).

## Deployment architecture (decided by measurement)

![Architecture diagram](architecture.png)

**Decision: edge Mobius (MEC host) + cloud Mobius, with the MEC app syncing to the cloud** — `config/site.yaml`

All 4 candidates were run on one PC, with `tools/wan_proxy.py` adding 25±5 ms one-way (about 50 ms round trip) on the site↔cloud link.
6 runs of the collision scenario each, `python tools/topology_bench.py` → `results/topology_25ms.json`.

| Configuration | Median / p95 alert latency | On-site alerts during WAN outage | Cloud copy | Edge CSE throughput |
|---|---|---|---|---|
| ① Cloud Mobius only | 85 / 133 ms | ❌ 0 (all stopped) | N/A | — |
| ② Edge Mobius only | 23.5 / 29 ms | ✅ | ❌ None | Headroom at 250 writes/s |
| **③ Edge Mobius + cloud sync** | **25 / 52 ms** | **✅ 26/26 kept** | **✅** | **Headroom at 250 writes/s** |
| ④ Edge ACME MN ↔ cloud Mobius (Mcc) | 33 / 43 ms | ✅ 26/26 kept | ✅ (via MN retargeting) | ❌ Saturates at ~110 writes/s |

Edge CSE load test (`tools/cse_load_bench.py`, 10 Hz per device, subscriptions on every container):

| Devices (requests/s) | Mobius write p95 | Mobius notify p95 | ACME throughput | ACME write p95 |
|---|---|---|---|---|
| 10 (100) | 10 ms | 12 ms | 100.7/s | 32 ms |
| 25 (250) | 63 ms | 71 ms | **109/s (saturated)** | 323 ms |
| 50 (500) | 205 ms (355/s) | 237 ms | 112/s | 642 ms |

Rationale
- **Availability is decisive.** With ①, no alerts go out at all when the cloud link drops. It cannot be used as a safety system.
  The latency gap (about 60 ms) is small next to the 2 s prediction lead time, but the behaviour during an outage differs as 0 vs 100%.
- **④ fails on scale.** 20 workers + 5 forklifts (10 Hz) is 250 requests/s, but ACME saturates at about 110/s and latency climbs to hundreds of ms.
  Mobius gives p95 63 ms under the same conditions (a conservative figure, measured on the same 2-core PC as the load generator).
- **③ keeps ②'s performance and adds a cloud copy.** Sync runs on a separate queue, so a slow or broken WAN does not affect on-site alerts (the 74 failures during the outage are counted in `/health`).
- Limitation: Mobius 3 is IN-CSE only, so edge and cloud Mobius are linked by MEC app sync, not oneM2M Mcc registration.
  Standard Mcc interworking was validated separately with configuration ④ (ACME MN → Mobius IN) and is kept for attaching low-rate gateways (camera nodes, etc.).

Run (assuming Mobius is already running on the edge server):
```bash
export EDGEGUARD_CONFIG=config/site.yaml      # change only cloud_sync.base_url to the cloud address
scripts/mec.sh start
python devices/device_sim.py --config config/site.yaml --start-delay 4 &
python tools/setup_resources.py --config config/site.yaml --reset
```
The Mobius 3.x CSEBase has `srv: ["1","2","2a"]`, so we use `rvi: "2a"`.

Issues found in interoperability testing and their fixes are documented in [docs/interop-notes.md](interop-notes.md).

## oneM2M resource tree

Each device registers **its own AE** (originator = that device). The MEC app writes its decisions to its own AE.

```
/Mobius (CSEBase)
├── worker_01 (AE, originator SWorker01)        worker tag registers itself at boot
│   ├── location (CNT)                          → CIN {id, kind:"worker", ts, x, y}
│   ├── relay (CNT)                             uploads positions of neighbours in a coverage hole on their behalf (D2D relay) {id: neighbour, relay: worker_01, ...}
│   ├── status (CNT)                            the device's own action acknowledgements {id, kind:"ack", hw, state, ts} → dashboard HW ✓ / FW ✓
│   └── acp_worker_01 (ACP)                     tag: all · MEC app/MEC-IPE: retrieve · subscribe · write · other devices: none
├── forklift_01 (AE, originator SForklift01)
│   ├── motion (CNT)                            → CIN {id, kind:"forklift", ts, x, y, speed, heading, yaw_rate, route?}
│   ├── relay (CNT)
│   ├── status (CNT)
│   └── acp_forklift_01 (ACP)
├── camera_01 (AE, originator SCamera01)
│   ├── detect (CNT)                            → CIN {kind:"camera", ts, persons:[{x, y}, ...]}
│   └── acp_camera_01 (ACP)
└── EdgeGuard (AE, originator SEdgeGuard = MEC app)
    ├── risk (CNT)                              per-pair risk summary {pairs:[{level, range, tcpa, dcpa, ttc, d_min, speed_scale, reason}]}
    ├── alert (CNT)                             alerts {event, level, worker, forklift, actions, reason, src_ts, mec_tx_ts}
    │                                            event: raise · refresh · clear (forklift + worker), wait · release · aside (worker only)
    ├── control (CNT)                           1 s heartbeat + reporting-rate commands {ts, hb, rates}
    ├── nearmiss (CNT, mni 2000)                near-miss records {worker, forklift, d_min, x, y, alerted}
    ├── mec_lease (CNT, mni 20)                 MEC app HA lease {id, seq, ts}
    └── acp_risk · acp_alert · acp_control · acp_nearmiss (ACP)   only the MEC app writes, devices read
```

| Subscription (SUB) | Target | Notified endpoint |
|---|---|---|
| `sub_mec` (plus `sub_mec_mec2` with HA) | `location` · `motion` · `detect` · `relay` of each device AE | MEC app `/notify` |
| `sub_devices`, `sub_hw<N>` | `EdgeGuard/alert`, `EdgeGuard/control` | Virtual devices · physical devices (`poa` = `http://<device>/alert`) |

- **Registration**: at boot, the firmware creates its AE and containers with `registerAE()` (409 if they already exist; it carries on).
  `tools/setup_resources.py` performs the same registration on the devices' behalf using their originators and attaches the ACPs (once, at site installation).
- **Access control**: no device can write to another device's AE. The MEC app reads and subscribes, and only the MEC app writes decisions.
  CI checks on every commit that forged writes are blocked on Mobius (`deploy/check_acl.py`).
- **D2D relay**: a relaying device uploads a neighbour's position from a coverage hole to the `relay` container of **its own AE**. Relay frames are authenticated with HMAC over the D2D link.
- The previous layout (device containers under a single AE) is still available via `layout: single_ae`.

## Firmware
- Worker tag: DW1000 two-way ranging → `firmware/common/uwb_position.h` (linearised least squares + Gauss–Newton, rejection of one NLOS anchor).
  Tested to match its Python twin `edgeguard/uwb.py` (mean error < 0.15 m at 0.1 m noise, rejects an NLOS anchor at +1.5 m).
- Both sketches handle the rate commands and heartbeat in `<ae>/control`; the forklift limits PWM according to the fail-safe rules above.
- `tests/test_firmware_build.py`: type-checks both sketches with `-Wall -Wextra -Werror` against the real ArduinoJson + ESP32 API stubs (also runs in CI).

## Installation and CI
- `scripts/setup_mobius.sh` — installs and starts Mobius 3 + MariaDB (`install | start | stop | status`). Converts the schema's MySQL 8 collations for MariaDB and automates the interactive secret setup.
- `.github/workflows/ci.yml` — full test suite on Python 3.11 on every push (including LSTM, CPU torch) + firmware type checks.
