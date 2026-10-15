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

## Firmware on MQTT, with a device certificate

The ESP32 firmware speaks the oneM2M MQTT binding too: build with `M2M_MQTT=1` ([`firmware/common/m2m_mqtt.h`](../firmware/common/m2m_mqtt.h), PubSubClient + WiFiClientSecure). Registration, samples and confirmations go out as request primitives over one TLS connection. With `MQTT_CLIENT_CERT` / `MQTT_CLIENT_KEY`, the device connects to the broker's **mutual-TLS listener (:8884)** with its own certificate and needs no password.

- **Certificates:** [`scripts/device_cert.sh`](../scripts/device_cert.sh) issues each device's key and certificate from the site CA (CN = originator), revokes old serials and regenerates the CRL. The broker takes the CN as the username, so the per-originator ACL applies, and it refuses revoked certificates.
- **CI, firmware in the loop:** the unmodified firmware, compiled for a PC, runs over HTTP, over MQTT/TLS with a password, and over mutual TLS with its certificate. All three runs pass 8/8 (`sil_run.py --transport mqtt | mqtt-mtls`).
- **CI, [`tools/device_identity_demo.py`](../tools/device_identity_demo.py), 7/7:** a device registers and publishes with its certificate only. Refused: no certificate, a certificate from another CA, impersonation, and a revoked certificate after rotation. The new certificate works.
- **Alerts over MQTT too ([`tools/mqtt_notify_demo.py`](../tools/mqtt_notify_demo.py), CI, 6/6):** a tag registers with point of access `mqtts://` and subscribes to its own alerts; the CSE delivers each alert as a NOTIFY on `/oneM2M/req/<CSE-ID>/<AE-ID>/json`. One TLS connection carries both directions: 30/30 alerts from the HTTPS app, in order, **p50 ≈ 10 ms**, p95 ≈ 13 ms (app → CSE → broker → tag). Another device listening on the tag's topic receives nothing (broker ACL). This works since ACME 2026.05.3, which fixed the outgoing-MQTT bug this project reported ([#200](https://github.com/ankraft/ACME-oneM2M-CSE/issues/200)).

## Secured transport ([`edgeguard/mqtt_binding.py`](../edgeguard/mqtt_binding.py))

| Path | Transport | Authentication |
|---|---|---|
| Device → CSE | oneM2M **MQTT binding (TS-0010) over TLS 1.2+** to the site broker (:8883); one connection, no inbound port | broker password per device, and an ACL that lets a device publish requests only under its own originator |
| CSE ↔ broker | MQTT over TLS, broker certificate verified against the site CA | broker password |
| Application ↔ CSE | **HTTPS** (:8443), CSE certificate verified against the site CA | oneM2M originator + ACP |
| CSE → application | HTTPS notifications to the application's own TLS endpoint | |
| CSE → device | oneM2M notifications over the MQTT binding (TLS), on the device's own topic | broker ACL: a device reads only notifications addressed to it |

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
- Applications receive notifications over HTTPS; devices receive them over MQTT (ACME ≥ 2026.05.3, see above). Older ACME releases fail on outgoing MQTT requests ([#200](https://github.com/ankraft/ACME-oneM2M-CSE/issues/200), fixed upstream after our report).
