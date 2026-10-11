# Issue drafts for ACME CSE (ankraft/ACME-oneM2M-CSE)

[← publishing checklist](../publish-checklist.md)

Two bugs we hit while building EdgeGuard. Both were checked on ACME master `a681a2f` (2026-10-08). Filed on 2026-10-11 as [#199](https://github.com/ankraft/ACME-oneM2M-CSE/issues/199) (HTTP Content-Type) and [#200](https://github.com/ankraft/ACME-oneM2M-CSE/issues/200) (MQTT NameError); both bugs were still present on ACME master that day.

---

## 1. HTTP binding: response `Content-Type` with media-type parameters is not recognised

Filed: [#199](https://github.com/ankraft/ACME-oneM2M-CSE/issues/199)

**Title:** HTTP client fails on responses with `Content-Type: application/json; charset=utf-8`

**Body:**

When ACME sends a request to another CSE over HTTP, for example an MN-CSE registering with a KETI Mobius IN-CSE, it cannot read the response. The cause is a `Content-Type` that carries a media-type parameter: Mobius answers with `application/json; charset=utf-8`.

In `acmecse/plugins/bindings/HttpServer.py` (`sendHttpRequest`, around line 554):

```python
resp.ct = ContentSerializationType.getType(r.headers.get('Content-Type', ct))
```

`getType()` compares the full header value, so `application/json; charset=utf-8` is not recognised and the response body is not deserialised. Media-type parameters are valid (RFC 9110 §8.3.1). A fix that worked for us:

```python
resp.ct = ContentSerializationType.getType(r.headers.get('Content-Type', ct).split(';')[0].strip())
```

**To reproduce:** start an ACME MN-CSE whose registrar is a Mobius 3 IN-CSE. The CSR registration fails because the response cannot be parsed.

**Environment:** ACME master (a681a2f), Python 3.11, KETI Mobius 3.0.1.

---

## 2. MQTT binding: outgoing requests fail with `NameError: name 'CSE' is not defined`

Filed: [#200](https://github.com/ankraft/ACME-oneM2M-CSE/issues/200)

**Title:** MQTTClient.sendMqttRequest: `NameError: name 'CSE' is not defined`

**Body:**

When the CSE sends a request over MQTT, for example a notification to an AE registered with an `mqtt://` or `mqtts://` point of access, the request fails:

```
response, responseTopic = CSE.request.waitForResponse(preq.request.rqi, Configuration.mqtt_timeout)
NameError: name 'CSE' is not defined
```

It is `acmecse/plugins/bindings/MQTTClient.py`, line 600. The module no longer imports `CSE`; this looks like a leftover from the move of the bindings into plugins. Incoming MQTT requests work. Only requests the CSE originates fail, so notifications never reach MQTT-registered AEs, and the request that triggered them waits for its timeout.

**To reproduce:**
1. Enable `[mqtt]` with a broker.
2. Register an AE over MQTT with `poa: ["mqtts://127.0.0.1:8883"]`.
3. Create a subscription with `nu = <AE-ID>`.
4. Create a contentInstance in the subscribed container.

**Environment:** ACME master (a681a2f), Mosquitto 2.0.18 with TLS, Python 3.11.

---

## Post for the oneM2M developer community (forum / Discord)

> **EdgeGuard: worker–forklift collision prediction on oneM2M + ETSI MEC (open source)**
>
> We built EdgeGuard for the 2026 oneM2M Hackathon. It covers every gap in TR-0077 clause 7 (ESTIMED), each running on ACME and checked in CI:
> - **MEC interworking:** a bidirectional MEC-IPE with SDT classes for MEC data; deploy by intent across MEC hosts
> - **Handover:** network-triggered handover between zone MN-CSEs, with 1.5–11 ms interruption and 0 samples lost
> - **Federated learning:** TR-0084 roles as resources, plus model delivery with canary and rollback
> - **Swarm:** forklift coordination through a `<group>`
>
> It also uses SDT flexContainers with SAREF semantics, `<group>` fan-out and `<pollingChannel>`, and the MQTT binding over TLS. Code: https://github.com/ljw22112/Edgeguard. Video: https://youtu.be/P2JI5ZG6PIg · Article: https://www.hackster.io/ahind012/edgeguard-stop-forklift-accidents-before-they-happen-e07309. Feedback on the resource design is very welcome!
