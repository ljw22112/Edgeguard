# Changelog

All notable changes. Versions follow the project's milestones; dates are 2026.

## Unreleased — 2026-10-31
- **Policy v3.1: the emergency brake holds while the person is in front** ([docs](docs/robustness.md#policy-v31-the-emergency-brake-holds-while-the-person-is-in-front)): after an emergency stop the truck stays at 0 while that person is ahead in its path (`AEB_LATCH`, 3 m ahead / 1.3 m aside), and within 1.8 m any closing speed is a collision course (`AEB_NEAR_M`); Python + firmware, equivalence tests. Large-scale test (8,000 fresh episodes, 34,644 conflicts): **0 collisions** (95 % upper bound 0.11 per 1,000; v3 2, v2 5, previous 30), close passes 238 -> 141 vs v2, same throughput. Site comparison: 0 collisions, 97.3 % [96.9-97.7].

## 2026-10-29
- **Policy v3: the tag checks GO itself** ([docs](docs/robustness.md#policy-v3-the-tag-checks-go-itself)): a WAIT that runs out unheard, or one given before an MEC silence and then cleared, ends only when walking on at the worker's last pace would not meet a truck (D2D state, Python + firmware); a truck standing before someone in its path stays stopped. Found by tracing v2's MEC-restart collisions. Development seeds: 2 -> 0 collisions, throughput and worker time unchanged; validation seeds: none.
- **Large-scale test with confidence intervals** (`sim/large_eval.py`): 1,000 fresh episodes for the site comparison (EdgeGuard 0 collisions in 3,617 conflicts, 97.4 % [97.0-97.7]; wide proximity alarm 0, 48.3 %; narrowed 49, 60.3 %) and 8,000 per policy under the 8 scenarios: previous policy 30 collisions (0.87 per 1,000 conflicts), v2 5 (0.14), **v3 2 (0.06 [0.02-0.21])**, v3 +4.8 to +9.9 points over the previous policy in every scenario. Charts `docs/img/large_eval*.png`.
- **Safety case** ([docs](docs/safety-case.md)): hazards, claims, arguments and the tests that are their evidence; assumptions and residual risk.
- **Stop-point guarantee** proved by property-based tests (`tests/test_stop_guarantee.py`, hypothesis, ~5,000 cases): a point received in time is never passed; a late one is overshot by at most the stopping distance; it holds through MEC silence; its placement keeps r_safe.
- **SDT speedLimit** reports the stop point and the plans the truck applies (`egs:spdLt` stpX/stpY/plans/aebAc); the MEC app confirms plans from the twin.
- Tried and not adopted, with measured downsides: green wave (two variants), alert-state restore, entry gate, UWB + IMU fusion, LSTM walking prediction, the three combined and re-trained, early GO, adaptive stop-point margin.
- CI on ubuntu-24.04, actions/checkout v5, setup-python v6.

## 2026-10-18
- **Robust policy v2 (glide)**: a worker stepping out of the truck's path - the truck rolls at the speed that reaches the stop point when he is out instead of braking into it and speeding up again; the stop point is lifted as soon as he has left the path. Refined by robust training, no collision on 2,000 validation episodes. Test: 300 episodes 0 collisions, throughput 96.8 -> 97.3 % (previous policy 91.8 %); 2,400 stressed episodes on two test sets: 2 collisions (v1 2, previous policy 8), mean throughput +0.3-0.6 points over v1.
- Electronic schematics of the tag and the forklift module (`tools/draw_schematic.py`).

## 2026-10-17
- **Truck priority with stop points** ([docs](docs/site-compare.md#truck-priority-stop-points-robust-training)): the worker yields (WAIT / STEP ASIDE), the truck keeps its speed inside its stopping envelope; for a person in its path it gets a stop point and brakes for it from its own position (Python + firmware); limits eased at once. Same 300 test episodes: 0 collisions, throughput 91.4 -> 96.8 % (previous policy, same devices), vs wide UWB proximity 2.0 x, vs narrowed 0 vs 12 collisions and +60 %. The +10 % goal was not reached (+5.9 %).
- **Robustness** ([docs](docs/robustness.md)): `sim/robust_eval.py` with 8 scenarios (normal, 85/70 % compliance, bad network, MEC restart, noisy UWB, dense, attentive). Fixes found by tracing collisions: always-on D2D emergency brake, tag WAIT kept through MEC silence while a truck is near, local rule 1.5 s after a silence, plan confirmation with re-send (MEC app + firmware), devices drop overtaken messages, sidesteps clear of every truck and never across the path, stop points that do not drift. Policy trained on the scenario mix (`--mode priority --robust`), picked with no collision on 2,000 validation episodes; test 1,200 stressed episodes: 1 collision (previous policy 3), throughput +5-9 points in every condition.
- **Policy learning on the many-to-many floor** (`sim/train_multi.py`, CEM, 15 parameters; training seeds 10,000+/20,000+, selection 3,000+, test 5,000+): stopping envelope near a person ahead (`env_cap`), walking direction learned only while walking, learned `config/site.yaml`. Same 300 test episodes: collisions 1 -> 0, throughput 86.6 -> 89.4 %, worker time lost 2.80 -> 2.71 s. Against the wide UWB proximity alarm: equally 0 collisions, +85 % throughput, -81 % alarms; against the narrowed one: 0 vs 12 collisions, +48 %. A refinement candidate (`sim/train_multi_refine.py`, +1.6 pt) was rejected for 4 collisions on 400 fresh validation episodes.

## 2026-10-16
- **Server stability** ([docs](docs/stability.md)): `tools/soak_test.py` (burst, camera churn, link outage, CSE state loss; CI 3.5 min). Fixed: after a CSE lost its state the MEC app never sent another alert (now rebuilds its tree, recovery in 2.1 s); supervised background loops with `/health` liveness; `/notify` queues and coalesces per device (slowest `/health` 358 -> 112 ms); side tables of forgotten tracks cleaned; client retries for ACME races (4117, subscription create/update).
- **Remaining collisions audited** (`sim/collision_audit.py`): the GO check used a wrong or missing walking direction (slow-down speed, sidestep, unknown). Fixed with the pre-alert direction at walking pace and a standoff rule; held-out 400 episodes: collisions 4 -> 2 at full compliance (not significant at 85 %), throughput -0.5 pt.
- **Efficiency audit** (`sim/efficiency_audit.py`): forklift time lost by reason; a truck no longer crawls past a worker who waits for another truck, and passes a standing worker well clear of its path at 2 m/s.
- **Comparison with site practice** ([docs](docs/site-compare.md)): no system, 5 km/h speed zoning, UWB proximity alarms (6/3 m and 4/2 m) and EdgeGuard on the same 300 episodes; charts in `docs/img/site_compare*.png`.
- ACME issue drafts 3-5 (startup race, orphaned subscription, dangling originator).

## 2026-10-15
- **ACME 2026.05.3**: the maintainer fixed both bugs this project reported (#199 Content-Type parameters, #200 outgoing MQTT requests). CI and `scripts/acme.sh` moved to that release. The earlier CI break came from ACME's requirements (numpy 2.5 needs Python >= 3.12): ACME's venv now uses Python 3.13.
- **Alerts over MQTT**: tags with an `mqtts://` point of access receive alerts as oneM2M notifications over the MQTT binding (`tools/mqtt_notify_demo.py`, 6 checks in CI, p50 ≈ 10 ms). The "notifications over HTTP only" limitation is gone.

## v1.6 — 2026-10-14

### Added
- **MEC platform APIs** ([docs](docs/mec-platform.md)): MEC 011 Mp1 (READY, service registration with a pointer to the zone CSE and AE, discovery, availability notifications); MEC 021 AMS as a handover trigger (move-out → context transfer to the target instance → oneM2M twin handover → completed); MEC 013 area and distance subscriptions requested from oneM2M through the MEC-IPE (`geoEvents`). `tools/mec_platform_demo.py`, 10 checks in CI.
- **Federated learning deployed by the orchestrator**: `edgeguard/fl_app.py` runs an FL client as a deployable MEC app; intent → deploy → discover → train → aggregate → infer at the edge, host crash (no move to another site), late join by intent. `tools/fl_deploy_demo.py`, 9 checks, threads and containers in CI.
- Judge-facing website (`site/`, EN/KO): live floor, alert path through oneM2M, architecture, standards, CI evidence, criteria map.
- CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue and PR templates, this changelog.

### Changed
- CI and `scripts/acme.sh` pinned ACME to a known-good commit (`ACME_REF` overrides) while the 2026.05.2/3 break was investigated.
- FL coordinator skips participants that stopped refreshing (`stale_s`); orchestration provisioning carries host and zone; app kinds via `app_class`.

## v1.5 — 2026-10-11/12
- ESTIMED / TR-0077 clause 7: event-driven bidirectional MEC-IPE with MEC SDT classes, network-triggered handover and mobility map; MEC app orchestration across hosts with one container per instance; forklift swarm; federated model delivery (canary, rollback) into the risk engine; zone broadcast via group + pollingChannel.
- Devices on the oneM2M MQTT binding over TLS down to the firmware; per-device certificates with mutual TLS, revocation and rotation; apps on HTTPS.
- Final video, hackster.io article, repository made public, two ACME issues reported (#199, #200).

## v1.4
- SDT flexContainer data model (labels, discovery onboarding, SAREF semantics, chty ACPs), CSE handover between zone MN-CSEs, federated learning through oneM2M, AI safety agent over MCP.

## v1.3
- Per-device oneM2M AEs and ACPs (forged writes rejected, verified in CI), firmware in the loop on a PC, phone as worker tag, hardware demo kit, user study kit, English documentation.

## v1.0 – v1.2
- Blind-corner site map, D2D frame authentication, MEC app HA, near-miss analysis (v1.0); WAIT → GO cue (v1.1); many-to-many validation, standoff resolution, STEP ASIDE, fewer false alarms (v1.2).

## v0.6 – v0.9
- Collision-course test and learned alert policy, adaptive reporting rate, restart failsafe (v0.6–0.7); graceful degradation to device-to-device decisions (v0.8); D2D state exchange and alert relay (v0.9).
