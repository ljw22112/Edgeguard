# Status (updated 2026-10-07, v0.7)

The final presentation is deliberately not being prepared yet; development comes first.
Everything below is in the README ("v0.7: 신뢰성 · 규모 확장", "해커톤 MEC Sandbox 정렬").

## Done in v0.7
- LSTM v2 (odd behaviour included) adopted; CTRV stays the closed-loop default (15 vs 23 collisions)
- Adaptive reporting rate (`edgeguard/rate_control.py`, `<ae>/control`), priority outbox, 1 s heartbeat
- Device fail-safe (`edgeguard/device_policy.py` = `firmware/common/device_policy.h`, cross-checked by test):
  hold during silence, stop after 2.0 s (swept 1.3-3.0 s), lift a stale limit only while the MEC app is heard
- Firmware: UWB positioning, rate commands, heartbeat, fail-safe; host type-check in CI
- Cloud store-and-forward verified end to end: 25 s WAN cut, 56/56 alerts replayed, 0 duplicates
- MEC restart (1.4-2.2 s) and 40-device scale cases; MEC Sandbox alignment (MEC-IPE path, own scenario)
- `scripts/setup_mobius.sh`, GitHub Actions CI

## Scope (decided 2026-10-07)
No hardware validation. (Live ETSI MEC Sandbox: re-opened 2026-10-07 at the team's request, run from
the team laptop because this workspace cannot reach try-mec.etsi.org - see "Live ETSI MEC Sandbox" below.) Everything is validated with the
online / fast closed-loop simulations, real Mobius / ACME CSEs, the MEC stand-ins (mec_mock,
tools/mec_ipe.py) and our own Sandbox scenario. Firmware stays a reference implementation
(host type-check + cross-test against edgeguard/device_policy.py and edgeguard/uwb.py).

## Live ETSI MEC Sandbox (try-mec.etsi.org) - DONE 2026-10-07: CONNECTED (results/etsi_sandbox_live.json)
Note: the dashboard shows location/v2 but only location/v3 answers.
Validated locally against mec_mock posing as the Sandbox (CONNECTED: 6 UE containers, 8 subscriptions,
6 fixes/s, 16 alerts). On the PC, after deploying a scenario and starting UE movement in the dashboard:
```
cd ~\Edgeguard\deploy; git pull; docker compose up -d --build
docker compose run --rm sandbox-setup <base URL>      # add --vehicle-mps 1.5 if vehicles are slow
docker compose --profile sandbox up -d --force-recreate
docker compose run --rm sandbox-check                 # -> deploy/sandbox/report.json
```
Then record report.json as results/etsi_sandbox_live.json, README + roadmap (w1d).
Leave Sandbox mode: delete deploy/sandbox/overrides.yaml and `docker compose up -d --force-recreate mec`.

## Self-hosted Sandbox (DONE 2026-10-08: 8 pairs, 70 alerts in 2 min - results/sandbox_selfhosted_live.json)
Team desktop (Ryzen 7 9800X3D, 32 GB, Windows 11 Enterprise LTSC, 723 GB free) hosts a Hyper-V VM running
AdvantEDGE v1.9.2 (base of the ETSI MEC Sandbox) with our warehouse scenario. Procedure: deploy/sandbox-host/README.md
(create-vm.ps1 -> Ubuntu 22.04 at 192.168.200.10 -> install-runtime.sh -> install-advantedge.sh -> import scenario ->
sandbox-setup http://host.docker.internal:8088/<sandbox>).
2026-10-08: VM installed, all 19 AdvantEDGE pods Running after fix-images.sh (debian 12 base, bitnamilegacy plain tags,
minideb bookworm, registry.k8s.io kube-state-metrics). Next: import warehouse scenario, connect EdgeGuard.

## Remaining
- Docker deployment (w4a): done - images + compose stack, CI builds/tests/publishes to GHCR (README "MEC 호스트 배포").
- Final report / demo video / slides (W7) - not started on purpose

## Environment recovery (new session)
```bash
git clone https://github.com/ljw22112/Edgeguard.git edgeguard && cd edgeguard
pip install -r requirements.txt -r requirements-ml.txt pytest --break-system-packages
MOBIUS_DIR=$PWD/../Mobius scripts/setup_mobius.sh          # MariaDB + Mobius on :7579
git clone --depth 1 https://github.com/bblanchon/ArduinoJson.git /tmp/claude-0/arduinojson
python -m pytest -q
```

## MEC Sandbox (organizer answers, 2026-10-06; TR-0086 draft, rollout expected the week of 10/6)
**Applied 2026-10-06** (location_source: cse, tools/mec_ipe.py, scenarios/edgeguard-warehouse.yaml, tools/sandbox_e2e.py; see README). Live Sandbox integration is out of scope (2026-10-07); kept for reference.

- When connected to a CSE, the CSE registers AEs with the MEC host (no separate MEC 011 registration).
- UE positions are written into CSE resources by MEC-IPE → **the preferred path is reading location from oneM2M resources**.
  Devices injecting positions directly via primitives counts as a weaker approach "with exceptions" → argue UWB as the exception (sub-metre accuracy needed for collision avoidance indoors) and use MEC-IPE location as a secondary source (zone presence, fallback when the tag is missing).
- UEs only exist in scenarios. **Building our own scenario with our own map and tracks is strongly encouraged** → export the warehouse map plus worker/forklift tracks from sim/scenarios.py in the sandbox scenario format.
- Calling MEC APIs directly is allowed for exploration, but going through oneM2M resources is preferred → switch mec_services to read via CSE resources (keep the direct call as an option).
- Host requirements: see the sandbox repo README. A shared host will be provided (no sudo).
- API access (answered 2026-10-07): logging in to the Sandbox allocates a k8s namespace (the sbx... id in the URL);
  services under that namespace are reachable once a network scenario is deployed - no extra token. Matches our live run.
- Self-hosted Sandbox (organizer's setup): VM with 4 cores, 9 GB RAM, 80 GB disk, Ubuntu 24.04 (22.04 also works).
  Needed to load our own warehouse scenario (scenarios/edgeguard-warehouse.yaml) - the public Sandbox offers preset scenarios.
