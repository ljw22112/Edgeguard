# Federated learning through oneM2M (TR-0084)

[← README](../README.md) · [한국어](ko/federated-learning.md)

**Why.** The risk engine predicts workers with constant velocity, which is wrong exactly when people slow down into a stop or a turn. A learned model helps, but worker trajectories are personal data. So each site (the MEC host of a warehouse) trains on its own data, and **only model weights travel through oneM2M**. The coordinator never sees a position.

**Model.** A small MLP (16 → 24 → 4) adds a residual to the constant-velocity guess. From the last 0.8 s of velocity it predicts the displacement 1 s and 2 s ahead. Code: [`edgeguard/fl.py`](../edgeguard/fl.py).

## oneM2M resources

```
EdgeGuardFL (AE, coordinator, IN-CSE)
  task          egs:flTsk   modelName, rounds, currentRound, clientsPerRound, quorum, minSamples,
                            localEpochs, learningRate, roundTimeout, taskStatus, modelVersion
  rounds        CNT         one CIN per round: {round, selected, model_version, deadline_ms, epochs, lr}
  models        CNT         one CIN per version: {version, parent, round, participants, weights, metrics}
  acp_fl        coordinator: all · clients: read, discover, notify, create subscriptions only
fl_<site> (AE, one per client, created by the client)
  participant   egs:flPrt   site, sampleCount, available, computeScore, lastRound, modelVersion, participantStatus
  updates       CNT         one CIN per round it trained: {round, n, weights, loss, base_version}
  acp_fl        client: all · coordinator: read, discover, notify, create subscriptions only
subscriptions   each client → rounds (am I selected?) · coordinator → every updates container
```

## A round

1. **Discover** participants by label (`egs:fl/participant`) and read their status. Clients that registered since the last round join here.
2. **Select** up to `clientsPerRound` clients that are available and have at least `minSamples`, preferring the ones that waited longest, then the highest compute score.
3. **Announce** the round: a CIN in `rounds`. Each selected client trains from the latest model in `models` and posts its weights to its own `updates`.
4. **Aggregate** with FedAvg (weighted by sample count) when all selected clients answered or the timeout passed. This needs at least `quorum` updates based on the current version; otherwise the round is repeated with the model kept.
5. **Publish** the new version with its parent and participants (lineage), and update `task.modelVersion`.

## Run

```bash
scripts/acme.sh start in
python tools/fl_demo.py            # 8 checks, also in CI; results/fl.json
```

**Scenario:**
- Seoul, Busan and Incheon start.
- Incheon's MEC host fails mid-training in round 3, and the round is aggregated from the other two (quorum 2).
- Daejeon registers before round 4 and is selected immediately.
- Incheon comes back online in round 6.

| 2 s prediction error, held-out data, mean over 4 sites | m |
|---|---|
| Constant velocity | 0.604 |
| Each site training alone (evaluated on all sites) | 0.521 |
| **Federated global model** | **0.486** |

**Checks:**
- the task resource tracks the run
- the offline client is never selected while offline
- dropout tolerated
- late join selected
- updates carry only weights (no positions; size = 4 bytes × parameters)
- model lineage complete
- the global model beats constant velocity on every site
- the global model generalizes better than models trained alone

## Limits

- Walking data comes from a site simulator with per-site layouts, pace and stop/turn habits, not from measured tags.
- The learned model is not yet used by the online risk engine. Model delivery to the MEC apps is the next step.
- The study ran on ACME. The design follows the ESTIMED proof-of-concept roles and is meant to run on the ESTIMED VM.
