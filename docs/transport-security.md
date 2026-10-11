# Zone broadcast and secured transport

[← README](../README.md) · [한국어](ko/transport-security.md)

## Zone broadcast: `<group>` fan-out to tags behind NAT ([`edgeguard/zones.py`](../edgeguard/zones.py))

A zone-wide message must reach every tag in the zone at once: a forklift entering a pedestrian zone, a blind-corner caution, or stop-all. The MEC app keeps **one oneM2M `<group>` per zone**. Its members are the `alerts` containers of the tags currently in that zone, rewritten as tags move. A message is **one request** to `<group>/fopt`, and the CSE creates it in every member.

Tags on Wi-Fi / LTE behind NAT cannot take inbound connections, so they register with `rr=false`:
- each tag subscribes its own `alerts` container with its AE-ID as the notification target
- the CSE queues the notification in the tag's **`<pollingChannel>`**
- the tag long-polls `pch/pcu` and answers through the same channel, because ACME waits for that response

The `alerts` container's ACP lets the MEC app create contentInstances there and nothing else (`chty 4`).

In the MEC app (`onem2m.zone_broadcast` in `config/local-acme.yaml`), membership follows the tracks every second. A DANGER alert is sent to every tag in the forklift's zone, at most once every 3 s per forklift. `tools/setup_resources.py` gives each worker twin its inbox and polling channel.

```bash
python tools/zone_demo.py          # 9 checks -> results/zones.json
```

**Results:**
- one request reaches exactly the 3 tags in zone A
- when a tag walks into zone B, the groups are rewritten and the next zone B message reaches exactly the zone B tags
- fan-out plus polling delivery: **p50 ≈ 8–19 ms, p95 ≈ 10–24 ms** (CI)

**Refused (403):**
- another originator writing a tag's alerts
- the MEC app subscribing to a tag's alerts
- the MEC app reading a tag's polling channel

`deploy/check_sdt.py` also checks, in the end-to-end SDT run, that every tracked tag is in its zone's group.

## Secured transport ([`edgeguard/mqtt_binding.py`](../edgeguard/mqtt_binding.py))

| Path | Transport | Authentication |
|---|---|---|
| Device → CSE | oneM2M **MQTT binding (TS-0010) over TLS 1.2+** to the site broker (:8883); one connection, no inbound port | broker password per device, and an ACL that lets a device publish requests only under its own originator |
| CSE ↔ broker | MQTT over TLS, broker certificate verified against the site CA | broker password |
| Application ↔ CSE | **HTTPS** (:8443), CSE certificate verified against the site CA | oneM2M originator + ACP |
| CSE → application | HTTPS notifications to the application's own TLS endpoint | |

[`scripts/certs.sh`](../scripts/certs.sh) creates a demo site CA, the server certificate and random broker passwords in `.certs/`, which is not committed. [`scripts/mqtt.sh`](../scripts/mqtt.sh) runs Mosquitto, TLS only, with passwords and the per-originator ACL. `scripts/acme.sh start sec` starts the secured CSE ([`scripts/acme-sec.ini`](../scripts/acme-sec.ini)).

`MqttOneM2MClient` has the same API as the HTTP client, so devices and tools switch transport without code changes.

```bash
scripts/mqtt.sh start && scripts/acme.sh start sec
python tools/secure_transport_demo.py      # 10 checks -> results/secure_transport.json
```

**Results:**
- a forklift registers and publishes 50 samples over MQTT/TLS
- the MEC app receives all 50 as HTTPS notifications: device → CSE → app **p50 ≈ 24–36 ms** (CI / local)
- the app reads over HTTPS

**Refused:**
- plaintext HTTP to the CSE port
- a certificate not issued by the site CA
- plaintext MQTT
- a wrong broker password
- forklift credentials used to send as `Cworker01`: the broker ACL drops it, so there is no response
- another authenticated device reading the forklift's data: oneM2M ACP, 403

**Notes:**
- ACME's HTTP server is set to server-authenticated TLS. With `verifyCertificate=true` it would demand client certificates, but it loads no CA to check them against.
- ACME's current MQTT binding fails when the CSE *sends* requests over MQTT. For that reason, notifications go to applications over HTTPS rather than to MQTT-registered AEs; the client already handles MQTT notifications.
