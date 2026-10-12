# MEC application orchestration through oneM2M

[← README](../README.md) · [한국어](ko/orchestration.md) · [TR-0077 mapping](estimed-mapping.md)

The ESTIMED PoC's orchestration flow is discover → select → deploy → register → provision: oneM2M carries intent, identity, resources and status, and the MEC platform carries the execution lifecycle. [`edgeguard/orchestration.py`](../edgeguard/orchestration.py) implements that flow for EdgeGuard. All state is in oneM2M, so any oneM2M application, including the AI agent, can see where EdgeGuard runs and why. An operator deploys by creating **one resource**.

```
<host>/host            egs:mecHs   self-registered MEC host: zone, free CPU / memory, RTT to the site,
                                   lifecycle API; updated every second (heartbeat = lastModifiedTime)
EGOrch/intent_<name>   egs:depIn   intent: app, zone, CPU, memory, max latency
                                   -> orchestrator writes intentStatus, placement, appEntity
app-<instance>         AE          the deployed instance registers itself (lbl egs:app/<name>)
  config               CNT         provisioning: which device data to subscribe to
  status               CNT         heartbeat + work counter
```

| Step | What happens |
|---|---|
| Discover | label discovery `egs:mec/host`; each `egs:mecHs` is read, and its age is taken from `lt` |
| Select | constraints: host up, heartbeat < 2.5 s old, CPU / memory free, RTT ≤ max latency, zone (or a zone-less regional host). Ranking: same zone, then lowest RTT, then most free CPU |
| Deploy | `POST <lcmUr>/app_instances` (simplified MEC 010-2: instantiate, query, terminate). A host without capacity answers 409 and the next candidate is tried |
| Register | the instance creates its own AE, `config` and `status`, and subscribes to its `config` |
| Provision | the orchestrator, an owner of the device ACPs, adds the instance's originator (RETRIEVE, NOTIFY, CREATE of subscriptions only), then writes the configuration. The instance subscribes to the device data |
| Running | first `status` heartbeat; the intent shows `running`, `plcmt`, `appAe` |
| Monitor | a host heartbeat older than 2.5 s means the host is lost. The intent goes to `migrating`, is placed again with that host excluded, and the old instance's ACP grants are revoked |

## Demo (CI on every commit)

```bash
scripts/acme.sh start in
python tools/orchestration_demo.py      # 11 checks -> results/orchestration.json
```

**Hosts:**

| Host | Zone | CPU | RTT to the site |
|---|---|---|---|
| host-a1 | A | 4 | 2 ms |
| host-a2 | A | 2 | 4 ms |
| host-cloud | regional | 16 | 25 ms |

**Intents and placements:**

| Intent | Requirements | Placed on |
|---|---|---|
| edgeguard-risk | zone A, 2 CPU, ≤ 10 ms | **host-a1** |
| site-analytics | 8 CPU, ≤ 100 ms | **host-cloud** |
| edgeguard-risk-xl | 64 CPU | **unschedulable** (nothing deployed) |
| host-a1 crashes (no heartbeat, API gone) | | risk engine **re-placed on host-a2** |

**Measured in CI:**
- intent → running in ≈ 0.75 s
- host crash → detected after ≈ 1.9–2.4 s
- running again on host-a2 after ≈ 2.3–2.7 s
- the new instance processes the forklift's live data
- the old instance can no longer read it (403)

**Checks:**
- hosts found by label
- placements as above
- unschedulable intent
- full lifecycle order
- intent resource shows status, placement and app AE
- deployed instance processes live data
- re-placement after the crash
- live data again after re-placement
- old grants revoked
- only operators may submit intents

**Containers.** With `--runtime docker` (also in CI), every instance is its own container, run from the image [`deploy/edge-app/Dockerfile`](../deploy/edge-app/Dockerfile) with `docker run --network host --cpus/--memory` from the intent. The container registers its own AE, is provisioned and processes live data. When the host crashes, its containers are gone and the replacement starts as a new container on host-a2. The demo has 12 checks, one of them verifying the containers with `docker ps`: host-a1, then only host-a2.

**Limits.** The hosts and their lifecycle API are simulated, and the three hosts share one Docker daemon.
