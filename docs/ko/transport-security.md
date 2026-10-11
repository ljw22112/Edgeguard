# 구역 방송과 보안 전송

[← README](../../README.ko.md) · [English](../transport-security.md)

## 구역 방송: NAT 뒤 태그로 `<group>` 팬아웃 ([`edgeguard/zones.py`](../../edgeguard/zones.py))

구역 전체 메시지는 그 구역의 모든 태그에 한 번에 닿아야 합니다. 보행 구역에 들어오는 지게차, 사각 코너 주의, 전체 정지 같은 경우입니다. MEC 앱은 **구역마다 oneM2M `<group>` 하나**를 둡니다. 멤버는 지금 그 구역에 있는 태그들의 `alerts` 컨테이너이고, 태그가 움직이면 다시 씁니다. 메시지는 `<group>/fopt`로 보내는 **요청 한 번**이고, CSE가 모든 멤버에 만듭니다.

NAT 뒤의 Wi-Fi/LTE 태그는 들어오는 연결을 받을 수 없어 `rr=false`로 등록합니다.
- 각 태그가 자기 AE-ID를 알림 대상으로 해서 자기 `alerts` 컨테이너를 구독
- CSE가 알림을 태그의 **`<pollingChannel>`**에 대기시킴
- 태그는 `pch/pcu`를 롱폴링하고, ACME가 응답을 기다리므로 같은 채널로 응답함

`alerts` 컨테이너의 ACP는 MEC 앱에 contentInstance 생성만 허용합니다(`chty 4`).

MEC 앱(`config/local-acme.yaml`의 `onem2m.zone_broadcast`)은 매초 트랙에 맞춰 멤버십을 갱신합니다. DANGER 경보는 지게차가 있는 구역의 모든 태그로 보내고, 지게차당 3 s에 한 번까지만 보냅니다. `tools/setup_resources.py`가 각 작업자 트윈에 수신함과 폴링 채널을 만들어 줍니다.

```bash
python tools/zone_demo.py          # 9개 검사 -> results/zones.json
```

**결과:**
- 요청 한 번이 구역 A의 태그 3개에 정확히 도달
- 태그가 구역 B로 걸어가면 그룹을 다시 쓰고, 다음 구역 B 메시지는 구역 B 태그에만 도달
- 팬아웃 + 폴링 전달: **p50 ≈ 8–19 ms, p95 ≈ 10–24 ms**(CI)

**거부(403):**
- 다른 발신자가 태그 경보를 쓰는 것
- MEC 앱이 태그 경보를 구독하는 것
- MEC 앱이 태그 폴링 채널을 읽는 것

## 보안 전송 ([`edgeguard/mqtt_binding.py`](../../edgeguard/mqtt_binding.py))

| 경로 | 전송 | 인증 |
|---|---|---|
| 디바이스 → CSE | 사이트 브로커(:8883)로 oneM2M **MQTT 바인딩(TS-0010) over TLS 1.2+**. 연결 하나, 들어오는 포트 없음 | 디바이스별 브로커 비밀번호 + 자기 발신자로만 요청을 보낼 수 있게 하는 ACL |
| CSE ↔ 브로커 | MQTT over TLS, 사이트 CA로 브로커 인증서 검증 | 브로커 비밀번호 |
| 앱 ↔ CSE | **HTTPS**(:8443), 사이트 CA로 CSE 인증서 검증 | oneM2M 발신자 + ACP |
| CSE → 앱 | 앱 자체 TLS 엔드포인트로 HTTPS 알림 | |

`scripts/certs.sh`가 데모용 사이트 CA, 서버 인증서, 무작위 브로커 비밀번호를 `.certs/`에 만듭니다(커밋하지 않음). `scripts/mqtt.sh`는 TLS 전용 Mosquitto를 비밀번호와 발신자별 ACL로 실행합니다. `scripts/acme.sh start sec`는 보안 CSE를 시작합니다.

```bash
scripts/mqtt.sh start && scripts/acme.sh start sec
python tools/secure_transport_demo.py      # 10개 검사 -> results/secure_transport.json
```

**결과:**
- 지게차가 MQTT/TLS로 등록하고 샘플 50개를 게시
- MEC 앱이 50개 모두를 HTTPS 알림으로 수신: 디바이스 → CSE → 앱 **p50 ≈ 24–36 ms**
- 앱은 HTTPS로 조회

**거부:**
- CSE 포트로 평문 HTTP
- 사이트 CA가 발급하지 않은 인증서
- 평문 MQTT
- 틀린 브로커 비밀번호
- 지게차 자격증명으로 `Cworker01`인 척 보내기: 브로커 ACL이 버려서 응답 없음
- 인증된 다른 디바이스가 지게차 데이터를 읽기: oneM2M ACP, 403

**참고:** 현재 ACME MQTT 바인딩은 CSE가 MQTT로 요청을 *보낼* 때 실패합니다. 그래서 알림은 MQTT로 등록한 AE가 아니라 HTTPS로 앱에 보냅니다.
