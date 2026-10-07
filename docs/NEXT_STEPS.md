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

## Next up
1. When TR-0086 / the shared MEC Sandbox host is released: match MEC-IPE resource paths and content to
   `mec_services.ipe`, upload `scenarios/edgeguard-warehouse.yaml`, check UE addresses against `ue_map`,
   rerun `tools/sandbox_e2e.py` there; ask about API authentication.
2. Hardware (when parts arrive): flash both sketches, calibrate UWB anchors (w3b), check the fail-safe on the RC car.
3. MEC Docker image on the team PC (Docker Hub is blocked here) (w4a).
4. Optional: online sim case against the real Sandbox once it is reachable.

## Environment recovery (new session)
```bash
git clone https://github.com/ljw22112/Edgeguard.git edgeguard && cd edgeguard
pip install -r requirements.txt -r requirements-ml.txt pytest --break-system-packages
MOBIUS_DIR=$PWD/../Mobius scripts/setup_mobius.sh          # MariaDB + Mobius on :7579
git clone --depth 1 https://github.com/bblanchon/ArduinoJson.git /tmp/claude-0/arduinojson
python -m pytest -q
```

## MEC Sandbox (organizer answers, 2026-10-06; TR-0086 draft, rollout expected the week of 10/6)
**Applied 2026-10-06** (location_source: cse, tools/mec_ipe.py, scenarios/edgeguard-warehouse.yaml, tools/sandbox_e2e.py; see README). When the real sandbox opens: (1) match the MEC-IPE resource paths and content format to `mec_services.ipe`, (2) upload our scenario and check UE addresses against `ue_map`, (3) rerun `tools/sandbox_e2e.py` against the real environment.

- When connected to a CSE, the CSE registers AEs with the MEC host (no separate MEC 011 registration).
- UE positions are written into CSE resources by MEC-IPE → **the preferred path is reading location from oneM2M resources**.
  Devices injecting positions directly via primitives counts as a weaker approach "with exceptions" → argue UWB as the exception (sub-metre accuracy needed for collision avoidance indoors) and use MEC-IPE location as a secondary source (zone presence, fallback when the tag is missing).
- UEs only exist in scenarios. **Building our own scenario with our own map and tracks is strongly encouraged** → export the warehouse map plus worker/forklift tracks from sim/scenarios.py in the sandbox scenario format.
- Calling MEC APIs directly is allowed for exploration, but going through oneM2M resources is preferred → switch mec_services to read via CSE resources (keep the direct call as an option).
- Host requirements: see the sandbox repo README. A shared host will be provided (no sudo).
- Still unanswered: API authentication.
