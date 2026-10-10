# MEC 구역 간 CSE 핸드오버

[← README](../../README.ko.md) · [English](../handover.md)

큰 창고에는 여러 구역이 있고, 구역마다 MEC 호스트가 EdgeGuard MEC 앱 옆에서 **MN-CSE**를 실행합니다. MN-CSE는 Mcc로 **IN-CSE**에 등록합니다. 지게차 모듈이나 작업자 태그는 자신이 있는 구역의 MN-CSE에 SDT 트윈을 두고, 구역을 바꾸면 트윈을 옮깁니다. 코드: [`edgeguard/handover.py`](../../edgeguard/handover.py).

## 절차 (make-before-break)

| 단계 | 일어나는 일 |
|---|---|
| 트리거 | **위치**: 위치가 다른 구역 안으로 `hysteresis`(1 m) 들어감 · **가용성**: 연속 `fail_limit`(3)번 전송 실패 → CSE가 응답하는 가장 가까운 구역 |
| 준비 (백그라운드) | 샘플은 계속 원본으로 가는 동안: 원본 트윈에서 모듈 값을 읽음(**상태**) · 대상에 AE · 트윈 · ACP를 다시 만듦(**보안 컨텍스트**) · 트윈의 모든 구독을 같은 `nu`로 다시 만듦(**구독**) · 새 AE를 IN-CSE에 공지(`at`), AEAnnc의 `lnk`는 서비스 중인 CSE를 가리킴 |
| 전환 | 다음 샘플부터 대상으로 감 |
| 홈 기록 | `<IN-CSE>/<dev>/serving`에 `{zone, cse_id, poa, reason, prep_ms, subscriptions}`를 기록, 애플리케이션이 읽거나 구독함 |
| 해제 | `grace_s`(0.5 s) 뒤 원본 AE 삭제 |

**옮겨 가는 구독.** ACME에서 구독은 만든 쪽만 읽을 수 있습니다. 그래서 움직이는 장치를 따라가려는 구독자는 자기 구독에 장치의 ACP를 붙입니다(`create_subscription(..., acpi=[<device ACP>])`). 그러면 장치가 구독을 읽어 대상 CSE로 옮길 수 있습니다.

**가용성 장애 조치.** 원본을 더 이상 읽을 수 없습니다. 트윈은 장치 자신의 마지막 상태로 다시 만들고, 설정된 구독자(`handover.subscribers`)를 대상에서 구독시킵니다. 애플리케이션은 홈 기록으로도 변화를 알 수 있습니다.

준비에 실패한 대상은 5 s 동안 다시 시도하지 않습니다.

## 측정 (매 커밋 CI)

```bash
scripts/acme.sh start in mn-a mn-b          # IN-CSE :8080, 구역 A :8081, 구역 B :8082
python tools/handover_demo.py               # 위치: 10개 확인
python tools/handover_demo.py --failover    # + 구역 B의 CSE 종료: 8개 확인
```

| 핸드오버 | 준비 시간 | 서비스 중단 | 유실 샘플 |
|---|---|---|---|
| 위치 A → B | 100–130 ms (백그라운드) | **3–9 ms** | **0** |
| 가용성 (구역 B 다운) → A | 감지 후 ≈ 80 ms | ≈ 306 ms | 3 (감지 구간: 전송 실패 3번) |

서비스 중단은 구독한 애플리케이션에서 알림 사이 가장 큰 간격에서 샘플 주기 100 ms를 뺀 값입니다. 유실 샘플은 장치가 보냈지만 애플리케이션에 닿지 않은 샘플입니다.

**확인 항목:**
- 위치 트리거 (A → B)
- 유실 샘플 없음
- 서비스 중단 < 300 ms
- 대상에서 속도 제한 복원
- 대상에서 구독 복원
- 대상에서 다른 장치 거부 (ACP)
- IN-CSE의 공지가 구역 B를 가리킴
- 원본 AE 삭제
- 애플리케이션이 재구독 없이 계속 수신
- 홈 기록이 장치를 따라감
- `--failover`: 가용성 트리거 B → A · 알림 재개 · 홈 기록에 장애 조치 표시

결과: `results/handover.json`, `results/handover_failover.json`.

## 파일

| 파일 | 내용 |
|---|---|
| `scripts/acme-mn-a.ini`, `scripts/acme-mn-b.ini` | 구역 MN-CSE 설정 (IN-CSE에 등록) |
| `scripts/acme.sh` | SDT 도메인을 설치한 채 `in` · `mn-a` · `mn-b` 시작 · 종료 |
| `edgeguard/handover.py` | `HandoverClient` (attach, publish, 트리거, prepare, switch, release), `setup_home` |
| `tools/handover_demo.py` | 데모 · 측정 |

## 한계

- 트리거는 장치 자신의 위치를 씁니다. MEC Location 구역 이벤트로 트리거하는 것은 확장 가능한 부분입니다.
- 가용성 경로는 감지 중에 보낸 샘플을 잃습니다(10 Hz에서 ≈ 0.3 s). 실제 장치에서는 D2D 로컬 판단이 이 구간을 메웁니다.
