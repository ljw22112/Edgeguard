# Status (updated 2026-10-10, v1.2)

The final presentation is deliberately not being prepared yet; development comes first.
README is the short overview; details live in docs/ (risk-and-evaluation, resilience, site-features, deployment, mec-sandbox, adoption).

## Done in v1.2 (docs/risk-and-evaluation.md "v1.2")
- sim/multi_sim.py: 8 workers x 4 forklifts, 200 episodes.  Found and fixed: devices kept one plan / one wait
  (forklift limit per worker, tag WAIT per forklift, Python + C++); standoff release race (one side first:
  truck if its way is clear, else the worker); GO check over the truck's speed range incl. acceleration;
  STEP ASIDE for a worker standing on a truck's predicted path; intent frozen while stepping aside.
  Multi: collisions 100 -> 4 of 750, throughput 61.7 -> 86.0 %.  1:1: 145 -> 1 of 1207, 77.3 -> 86.4 %.
- False alarms: still gate (worker < 0.4 m/s predicted standing), optional route sharing (RoutePredictor,
  forklift samples may carry "route").  622 -> 570 -> 400 of 993.  results/false_alarm_eval.json.
- Dashboard shows WAIT / STEP ASIDE / GO per worker (MEC-side WaitCue mirror).
- Not adopted: min_move had no measurable effect after the other fixes (kept for physical reasons).

## Done in v1.1 (docs/risk-and-evaluation.md "v1.1")
- Root cause of the remaining collisions: all were timely alerts; the buzzed worker stopped ~2 s and walked on into
  a forklift planned for a worker who stays.  Fix: worker tag WAIT until GO (edgeguard/worker_cue.py +
  firmware/common/worker_cue.h, C++/Python cross-tested; gives up after 2.5 s without a message), MEC `wait`
  keep-alive every 1 s while the alert is active, GO check (no clear while walking on would cross the forklift).
  Forklift ignores worker-only events (wait / release).  sim: Mover.UX = "hold" (default), COMPLY sweep.
- Result (2,200 encounters, 2 seed sets): collisions 145 -> 11 (-92 %), forklift throughput 77.3 -> 81.7 %,
  worker +1.4 s per encounter.  50 % compliance still 44.  Outage conditions: normal 23 -> 0, dead zones 17/16 -> 1/1.
  results/worker_cue_eval.json, failsafe_eval_hold*.json.  Rejected: early release, trust_hold, shorter clear_hold,
  retraining for the new UX, LSTM.

## Done in v1.0 (docs/site-features.md, docs/resilience.md)
- Blind corners: config sitemap.obstacles, line-of-sight per pair (edgeguard/sitemap.py); occluded pairs get
  r_safe +0.5 m and debounce 1.  Blind-corner collisions 17 -> 11 of 80 (false alarms 39 -> 57 there only);
  a +1 s time margin was worse (22) and rejected.  results/occlusion_eval.json.
- D2D auth: HMAC-SHA256 8-byte tag + per-sender seq (fresh window 50, replay drop), firmware/common/d2d_auth.h,
  Python reference edgeguard/d2d_auth.py, byte-exact cross test.  Pre-shared site key.
- MEC HA: active-standby via lease in <AE>/mec_lease (renew 0.2 s, take-over after 0.6 s, immediate heartbeat),
  compose profile `ha` (MEC_HA=1, mec2 on 9092), CI kills the leader (deploy/check_ha.py).
- Monitoring: compose profile `monitoring` (Prometheus 9095, Grafana 3000, provisioned dashboard, 5 operator
  alert rules), CI check deploy/check_monitoring.py.
- Near-miss analytics: measured close passes < 2 m, alerted-before flag, 1 m heat map, hotspots with advice,
  <AE>/nearmiss, /nearmiss, dashboard overlay, safety report section.
- Fixed: OneM2MClient.with_retry dropped keyword args (setup crashed on mni=, stack CI was red for one commit).

## Done in v0.9
- Cooperative D2D (the "cars in a tunnel" idea): ESP-NOW state broadcast {x,y,vx,vy,mecOk}, local 2-D
  closest-approach rule while MEC is silent, one-hop relay (x3) of MEC alerts / heartbeats down and positions up
  for devices in radio shadows.  Worker dead zone 66 -> 16, forklift dead zone 52 -> 19 collisions of 180 at
  76 % throughput.  firmware/common/d2d.h + both sketches; Python/C++ cross-tested; results/d2d_sensitivity.json.

- Server hardening: late samples no longer reset tracks (jitter 50 ms: 178 resets -> 0), outbox TTL (no stale
  heartbeats), track/pair GC, /notify always 2000 + threadpool, clock-skew guard, subscription watchdog,
  /health degraded flag, /metrics (Prometheus).  tests/test_server_hardening.py.

## Done in v0.8
- Graceful degradation on network loss: MEC prediction -> local UWB (direct forklift<->tag ranging,
  distance + range-rate TTC, tag vibrates too) after 2 s of MEC silence -> stop under an active limit.
  Network down for a whole encounter: 180 -> 1 collisions at 54 % throughput (halt-all: 2 at 18 %).
  results/failsafe_eval.json / .png; Python + C++ (LocalGuard) cross-tested.
- Peer ranging without a new protocol: forklift DW1000 = mobile anchor 0x20NN (firmware done, needs hardware check);
  ranging sensitivity: results/peer_ranging_sensitivity.json.
- LSTM fed by time-resampled 10 Hz history (irregular / 2 Hz / lossy reports): results/lstm_irregular.json.

## Where work runs (from 2026-10-08)
jw works on the laptop (Galaxy Book2 Pro, 8 GB RAM). Heavy work (simulations, training, builds, tests,
evaluations) runs in the cloud workspace; the laptop only runs what needs jw's network: the Docker stack
for live Sandbox checks / demos (limit WSL to ~4 GB via %UserProfile%\.wslconfig), never the AdvantEDGE VM
(that stays on the 32 GB desktop; the laptop can reach it on the same LAN at http://<desktop-ip>:8088).

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
- Docker deployment (w4a): done - images + compose stack, CI builds/tests/publishes to GHCR (docs/deployment.md).
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
**Applied 2026-10-06** (location_source: cse, tools/mec_ipe.py, scenarios/edgeguard-warehouse.yaml, tools/sandbox_e2e.py; see docs/mec-sandbox.md). Live Sandbox integration is out of scope (2026-10-07); kept for reference.

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
