# Work in progress (paused 2026-10-06)

Picking up from here next time. The final presentation is deliberately not being prepared yet; development comes first.

## Done in this session (after v0.6, not yet in the README)
- **LSTM v2**: retrained on standard + odd scenarios (running / zigzag / reversing). Unseen motion: ADE 0.94 → 0.50 m. Original scenarios: 0.175 → 0.184 m. Offline FA 29.8% (v1 30.0%) → adopted.
  - Closed loop with the trained policy (`results/closed_loop_ctrv_vs_lstm.json`): CTRV 15 collisions vs LSTM 23. Even after retuning the policy for LSTM, the best was 22 (`results/policy_training_lstm.json`) → **CTRV stays as the deployment default**.
  - `sim/train_policy.py --method guidance_lstm --no-write` option added.
- **Cloud store-and-forward** (`edgeguard/cloud_sync.py`), **UWB positioning** (`edgeguard/uwb.py`, `firmware/common/uwb_position.h`), firmware host type-check (`tests/test_firmware_build.py`)
- **Mobius install script** `scripts/setup_mobius.sh` (install/start/stop/status, verified)
- **CI** `.github/workflows/ci.yml` (first run happens on this push; check it)
- **Online sim cases added** (`results/online_robustness.json`):
  - `scale_12` (24 devices, design load): p50 230 ms, 100% timely
  - `scale_20` (40 devices): CSE saturates on the 2-core test box → p50 2.5 s
  - Publisher changed to firmware semantics (superseded samples are skipped)
- **Adaptive reporting rate** `edgeguard/rate_control.py` + `<ae>/control` container (MEC app, setup_resources, sim):
  - 40 devices, sparse site, same encounters: collisions 9 → 1, alert latency p95 3.4 s → 1.1 s. No regression at normal load. `config/site.yaml` `rate_control.enabled: true`
- **MEC priority outbox** (alerts > control > risk) + **1 s heartbeat** (`<ae>/control`)
- **Device fail-safe** `edgeguard/device_policy.py` (`ForkliftLimit`, `ReportRate`); evaluation script `sim/failsafe_eval.py` → `results/failsafe_eval.json`
  - Conclusion: on a short outage, crawling or stopping immediately is **worse** than holding the plan. On a long outage (8 s), stopping is better.
  - Current setting: hold during silence, stop after `STOP_AFTER_S = 3.0` s of silence, never lift during silence
- **MEC restart test** `mec_restart` case: downtime 1.4–2.2 s, alerts resume after restart
- Sim metric fix: first alert = first non-clear event (raise or refresh)
- `tools/outage_replay_test.py` (WAN cut → recovery → check that every alert reaches the cloud) **written, not yet run**

## Next up, in order
1. **`STOP_AFTER_S` sweep** (1.3 / 1.6 / 2.0 / 2.5 / 3.0) → pick the trade-off between short outages (restart, restart+loss20) and long ones (mec_dead_8s). Was in progress when paused.
2. **Firmware**: forklift_module/worker_tag should handle `<ae>/control` notifications (`rates` → publish period, `hb` → heartbeat) and implement the `device_policy.py` rules (replacing today's 5 s lift with the hold → stop logic). Then run `tests/test_firmware_build.py`.
3. Run `python tools/outage_replay_test.py` (needs Mobius up) → `results/outage_replay.json`
4. Re-run the `mec_restart` and `scale_*` online cases with the final settings
5. README update: everything above (LSTM v2, adaptive rate, fail-safe, scale/restart, setup_mobius.sh, CI, UWB, store-and-forward)
6. Roadmap artifact: mark w6g (odd behaviour / LSTM retrain), w1b (Mobius install script) and w7d (README / install guide) done
7. Check the CI result: `gh api repos/ljw22112/Edgeguard/actions/runs`

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
