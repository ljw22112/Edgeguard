# Interview preparation: expected questions and answers

[← README](../README.md)

These are short answers for the finals interview (rubric item 9: the resource tree, the benefits of oneM2M, how the integration works). Every number comes from CI or from `results/`; the file behind each claim is named.

## oneM2M design

**Q1. Walk us through your resource tree.**
Each device is its own AE on the zone MN-CSE (`worker_01`, `forklift_01`), with its own ACP.
- The twin is a flexContainer from our SDT domain: `egs:wrkTg` for tags and `egs:frkMe` for forklift modules, with `kinematics`, `cue`/`speedLimit` and `cod:bat` modules.
- A SAREF semanticDescriptor sits next to it.
- The MEC app is its own AE, `EdgeGuard`, with `risk`, `alert`, `control` and `nearmiss` containers, plus one `<group>` per zone.
- The IN-CSE holds home records (`<dev>/serving`), announcements, the FL coordinator, the orchestrator and the AI agent's state.

[data-model.md](data-model.md), [deployment.md](deployment.md#onem2m-resource-tree).

**Q2. Why flexContainers and not plain containers?**
The device's state is typed and self-describing (`egs:kinSt` has `posX`, `speed`, `smpTe` and so on), so another application understands it without our code. An update notifies subscribers with only the changed module, and `mni` keeps the history as flexContainerInstances. New devices onboard by label discovery (`egs:module/kinematics`), with no device list: a self-registered tag is picked up in about 9 s.

**Q3. Which oneM2M features did you use that a plain MQTT broker would not give you?**
- discovery by label, and semantic queries (SAREF)
- ACPs with `accessControlObjectDetails`: the MEC app may create subscriptions but no data in a twin
- announcement and Mcc between zone MN-CSEs and the IN-CSE
- `<group>` fan-out: one request reaches every tag in a zone
- `<pollingChannel>` for tags behind NAT
- portable subscriptions that follow a device on handover

**Q4. How does CSE handover work, and what is preserved?**
Make-before-break:
1. The device keeps publishing to zone A while it rebuilds its twin on zone B: state, ACP, every subscription (subscribers attach the device's ACP so it can carry them) and the announcement.
2. It switches, updates its home record and releases zone A.

Triggers are location, CSE availability, or a MEC zone event. Results:
- location trigger: interruption 1.5–11 ms, 0 samples lost
- availability failover: about 0.3 s, with 3 samples lost in the detection window

[handover.md](handover.md).

**Q5. What happens if the network or the MEC app fails?**
The devices notice that the MEC heartbeat is missing and switch to local rules: UWB ranging between devices, D2D state exchange over HMAC-signed ESP-NOW, and alert relay to neighbours in coverage holes. They stop only when nothing else is known. In a total outage, collisions drop from 180 to 2 while forklifts keep 57 % throughput. A standby MEC app takes over in 0.73 s. [resilience.md](resilience.md).

## ETSI MEC integration (ESTIMED / TR-0077 clause 7)

**Q6. Where does EdgeGuard sit on the ESTIMED deployment continuum?**
Option C per zone: the MN-CSE, the MEC app and the MEC-IPE share the zone's MEC host. The IN-CSE runs in the cloud. [estimed-mapping.md](estimed-mapping.md).

**Q7. How do MEC services reach oneM2M applications, and the other way round?**
- **MEC → oneM2M:** the MEC-IPE subscribes to MEC 013 zone events and MEC 012 MeasRepUe reports and writes them as SDT twins (`egs:mecUe`, `egs:ueLoc`, `egs:rdLnk`) and zone-event contentInstances. Median latency is 15–45 ms.
- **oneM2M → MEC:** an application posts `{op: zone_subscribe | radio_subscribe | location}` into `MEC-IPE/requests`, and the IPE answers in `responses`. Applications never hold MEC credentials.

[mobility.md](mobility.md).

**Q8. How is a MEC application deployed?**
1. An operator creates one `egs:depIn` intent.
2. The orchestrator discovers hosts by label (`egs:mecHs`, with a one-second heartbeat) and selects one by zone, CPU, memory and latency.
3. It deploys through the host's lifecycle API. The instance is a real container (`deploy/edge-app`).
4. It waits for the instance to register its own AE, then provisions it: device ACP grant plus configuration.

When a host crashes, the instance is re-placed in about 2.5 s and the old grants are revoked. [orchestration.md](orchestration.md).

**Q9. How is federated learning done, and how does the model get to the edge?**
- **Learning:** TR-0084 roles as oneM2M resources: task, participants, rounds, and model versions with lineage. Participants are found by label, and dropout and late join are tolerated. Only weights travel. The 2 s prediction error goes from 0.604 m (constant velocity) to 0.486 m.
- **Delivery:** each site canaries a new version on its own held-out data, activates it in the risk engine (`guidance_fl`), shadow-evaluates the previous version, and rolls back on regression. The status is kept in `egs:mdlDp`.

[federated-learning.md](federated-learning.md), [swarm-and-model-delivery.md](swarm-and-model-delivery.md).

**Q10. What is "swarm" in your system?**
Forklifts in a zone form a `<group>` of their plan containers. Each member reads the whole context with one request (`<group>/fopt/la`) and computes the same conflict-free schedule itself, so no coordinator is needed. In the demo, conflicts drop from 4 to 0, with 14.5 s of total delay against 23.5 s for braking at each intersection.

## Security and privacy

**Q11. How do you secure devices?**
- Each device has its own certificate from the site CA, and its CN is its originator. The broker's mutual-TLS listener takes the CN as the identity, and its ACL lets a device publish only as itself.
- Revocation goes through a CRL; rotation means a new key plus revoking the old serial.
- Applications use HTTPS.
- In CI, these are refused: no certificate, a certificate from another CA, impersonation, a revoked certificate, plaintext and a wrong password.

[transport-security.md](transport-security.md).

**Q12. Does personal data leave the site?**
Worker trajectories stay in the zone's edge CSE. Only alerts, risk summaries and near-miss records (event positions) go to the cloud. Federated learning moves weights, never positions, and CI checks that.

## Engineering and evidence

**Q13. How do you know the firmware works without boards?**
The unmodified ESP32 firmware is compiled for a PC (software-in-the-loop) and talks to a real ACME CSE on every commit. It runs over HTTP, over the MQTT binding with TLS, and with device certificates. CI checks the WAIT/GO cue, the forklift speed limit, the beacon and the confirmations.

**Q14. Which interoperability problems did you find?**
Seven are documented in [interop-notes.md](interop-notes.md). Two ACME bugs are reported upstream:
- [#199](https://github.com/ankraft/ACME-oneM2M-CSE/issues/199): Content-Type with media-type parameters is not parsed.
- [#200](https://github.com/ankraft/ACME-oneM2M-CSE/issues/200): the MQTT binding cannot send requests.

The same code runs on ACME and KETI Mobius.

**Q15. What is simulated, and what is real?**
- **Real:** the oneM2M CSEs (ACME, Mobius), the MQTT broker with TLS, the containers, and the firmware compiled for a PC.
- **Simulated:** UWB error and people's behaviour (with sensitivity analyses), the MEC platform for events (`mec_mock` plays AdvantEDGE scenarios; the polling path ran on the ETSI Sandbox), and the MEC hosts.

The board demo and the user study are next.

**Q16. Why should a site adopt this rather than a proximity alarm?**
In our simulation baseline, 85 % of the alerts from a 5 m proximity alarm are false, so workers learn to ignore them. EdgeGuard predicts the collision course and tells each person what to do (WAIT, STEP ASIDE, GO), and collisions drop from 100 to 4 at higher forklift throughput (61.7 → 86 %). Because the data are standard oneM2M resources, the site's WMS or dashboards can use them without integration work. [business.md](business.md), [adoption.md](adoption.md).
