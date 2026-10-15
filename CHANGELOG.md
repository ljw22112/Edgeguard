# Changelog

All notable changes. Versions follow the project's milestones; dates are 2026.

## Unreleased — 2026-10-15
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
