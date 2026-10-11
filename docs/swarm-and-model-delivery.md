# Forklift swarm coordination and federated model delivery

[← README](../README.md) · [한국어](ko/swarm-and-model-delivery.md) · [TR-0077 mapping](estimed-mapping.md) · [Federated learning](federated-learning.md)

The ESTIMED PoC contrasts the two:
- **swarm computing** coordinates current behaviour: it shares bounded context, runs coordination cycles and produces recommendations, and participants keep local authority
- **federated learning** improves a model and produces a new model version

The PoC also notes that "aggregation ≠ operational model delivery". EdgeGuard does both, and closes the loop to the risk engine.

## Swarm (TR-0077 7.4): [`edgeguard/swarm.py`](../edgeguard/swarm.py)

```
sw_<forklift>            AE    member
  plan                   CNT   {"id", "prio" (1 = loaded), "route": [[intersection, eta_s], ...]}
  advice                 CNT   the start delay it adopted
<MEC AE>/swarm_<zone>    GRP   members = plan containers of the forklifts in the zone (MEC app keeps it current)
```

- **Membership:** a `<group>` per zone. Forklifts are added and removed as they enter and leave.
- **Context:** each member reads every member's latest plan with **one request** (`GET <group>/fopt/la`).
- **Coordination:** a deterministic schedule. Loaded forklifts go first, then the earliest arrival, then by id. Each forklift gets one start delay that keeps it 4 s from every earlier-scheduled forklift at every shared intersection.
- **Recommendations:** every member computes the schedule itself from the same context, so all members reach the same answer without a coordinator. Each publishes the delay it adopted.

```bash
python tools/swarm_demo.py      # 9 checks -> results/swarm.json
```

| Round | Conflicts without → with swarm | Total delay: swarm vs reacting at the intersection* |
|---|---|---|
| 4 forklifts | 4 → 0 | 14.5 s vs 23.5 s |
| fk2 leaves the zone | 3 → 0 | 12.0 s vs 18.0 s |
| loaded fk5 joins (goes first) | 7 → 0 | 25.5 s vs 62.0 s |

\* Reacting means first come, first served at each intersection: the later forklift brakes to a stop, waits, and pays 3 s for stopping and restarting. The context read takes ≈ 6–7 ms (median).

## Model delivery (TR-0077 7.3): [`edgeguard/model_delivery.py`](../edgeguard/model_delivery.py)

The FL coordinator publishes each global model in `EdgeGuardFL/models`. Each site's model manager, subscribed to it, runs three stages:

1. **Canary:** the new model is evaluated on the site's held-out walking data, against the active model (or constant velocity). It must be at least 2 % better, or it is rejected.
2. **Activate:** the risk engine (`method: guidance_fl`) predicts workers with it from the next sample. The predictor gives positions at 1 s and 2 s, linear in between.
3. **Monitor:** the active model is scored on live windows, and the previous version is shadow-evaluated on the same windows. If the previous version wins for 3 windows in a row, the manager rolls back.

Status lives in `<site>/model` (`egs:mdlDp`): version, previous version, status (canary / active / rejected / rolled_back), canary, baseline and live error. The history is kept as flexContainerInstances.

```bash
python tools/model_delivery_demo.py      # 8 checks -> results/model_delivery.json
```

| Version | Busan held-out error (2 s) | Decision |
|---|---|---|
| v0 untrained | 1.262 m vs constant velocity 0.577 m | rejected |
| v1 global (4 sites) | 0.468 m | **activated** |
| v2 corrupted update | 3.783 m | rejected (v1 kept) |
| v3 specialised on Busan | 0.400 m vs v1 0.468 m | **activated** |
| layout change (narrow aisles, frequent stops) | live: v3 0.62 m vs shadow v1 0.47 m | **rolled back to v1** |

Delivery from the coordinator's publish to the site's decision takes ≈ 15–30 ms. The demo trains its models directly; [`fl_demo.py`](../tools/fl_demo.py) runs the federated rounds.
