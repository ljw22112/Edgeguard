# MEC 플랫폼 API 위의 EdgeGuard: Mp1, AMS, 지오펜스

[← README](../../README.ko.md) · [English](../mec-platform.md) · [모빌리티](mobility.md) · [TR-0077 매핑](estimed-mapping.md)

MEC 앱은 위치(MEC 013)와 RNIS(MEC 012) 말고도 자기 플랫폼과 대화합니다. EdgeGuard는 ETSI MEC API 세 가지를 더 씁니다. 클라이언트는 [`edgeguard/mec_platform.py`](../../edgeguard/mec_platform.py)와 MEC-IPE([`edgeguard/mobility.py`](../../edgeguard/mobility.py))에, 플랫폼 쪽은 [`mec_mock/platform.py`](../../mec_mock/platform.py)에 있습니다.

| API | EdgeGuard의 사용 |
|---|---|
| **MEC 011 Mp1**: 앱 활성화, 서비스 관리 | 인스턴스마다 `READY`를 알리고 `edgeguard-safety` 서비스를 등록합니다. `transportInfo.implSpecificInfo.oneM2M`에 구역 CSE와 AE를 적어서, Mp1만 아는 MEC 앱도 oneM2M 리소스를 찾습니다. MEC-IPE는 고정 URL이 아니라 **Mp1로 찾은 Location 서비스**를 씁니다. 서비스 가용성 알림으로 다른 인스턴스의 등장과 퇴장을 압니다. |
| **MEC 021 AMS**: 앱 이동 서비스 | 구역마다 인스턴스가 담당 지게차를 등록하고(`APP_MOBILITY_PERMITTED_WITH_CONTEXT_TRANSFER`) 이동 절차를 구독합니다. AMS가 디바이스 위치, CSE 가용성, MEC 구역 이벤트에 이어 **oneM2M CSE 핸드오버의 트리거 주체**가 됩니다. |
| **MEC 013 영역 · 거리 구독** | oneM2M 앱이 `MEC-IPE/requests`로 요청합니다(`area_subscribe`, `distance_subscribe`). 이벤트는 `MEC-IPE/geoEvents`에 `{kind, ue / ues, event, mec_ts, ipe_ts}`로 기록됩니다. 영역은 원형 지오펜스(예: 상하차장), 거리는 "작업자와 지게차가 5 m 안"입니다. 거리는 태그와 별개로 네트워크가 자기 측위로 계산합니다. |

## AMS가 트리거하는 핸드오버

```
forklift_01이 구역 B(MEC 호스트 mep-b)로 진입
 AMS ──INTERHOST_MOVEOUT_TRIGGERED(대상 edgeguard-b, commInterface)──▶ edgeguard-a
 edgeguard-a ──안전 컨텍스트(마지막 샘플, 위험 상태)──▶ edgeguard-b        (대상의 commInterface)
 edgeguard-a ──network_trigger("B", reason=ams)──▶ oneM2M 트윈: MN-CSE B로 make-before-break
 edgeguard-a ──PUT USER_CONTEXT_TRANSFER_COMPLETED──▶ AMS
 AMS ──INTERHOST_MOVEOUT_COMPLETED──▶ edgeguard-a
```

플랫폼이 단말의 호스트가 바뀌었다고 판단한 순간, 앱 컨텍스트(MEC 쪽)와 디바이스 트윈(oneM2M 쪽)이 한 절차로 함께 이동합니다.

## 데모 (매 커밋 CI)

```bash
scripts/acme.sh start in mn-a mn-b
python tools/mec_platform_demo.py     # 10개 검사 -> results/mec_platform.json
```

시나리오는 [`edgeguard-two-zones.yaml`](../../scenarios/edgeguard-two-zones.yaml)이고 `MEC_MOCK_HOSTS=zoneA=mep-a,zoneB=mep-b`를 씁니다. 지게차가 4 m/s로 A → B → A를 달리며 worker_01 옆을 두 번 지나갑니다.

| 검사 | 결과 |
|---|---|
| Mp1: 두 인스턴스 READY, 두 호스트 모두에서 `edgeguard-safety`를 CSE ID · AE와 함께 탐색 | 통과 |
| Mp1: Location · AMS 서비스 탐색, IPE가 탐색한 Location 엔드포인트 사용 | 통과 |
| Mp1: 가용성 알림 ADDED × 2, 등록 해제 시 REMOVED | 통과 |
| AMS: A → B, B → A 이동 트리거, 각각 상대 호스트 인스턴스로 | 통과 |
| AMS: 안전 컨텍스트를 대상 commInterface로 전달(약 2~20 ms) | 통과 |
| AMS 트리거: oneM2M 트윈 A → B → A, 사유 `ams` | 통과 |
| AMS: 전송 완료 보고 뒤 `INTERHOST_MOVEOUT_COMPLETED` | 통과 |
| 영역: 6 m 지오펜스 안에서 ENTERING, 밖에서 LEAVING, GIS 갱신 한 번 이내(4 m/s에서 2 m) | 통과(중심에서 4.4 m / 7.6 m) |
| 거리: worker_01과 forklift_01이 5 m 안, 실제 간격 3.8~4.0 m | 통과 |
| MEC 013 구독을 oneM2M으로 해제 | 통과 |

지오펜스 · 거리 이벤트는 플랫폼 발생 후 약 10 ms에 oneM2M에 도착합니다.

단위 시험: [`tests/test_mec_platform.py`](../../tests/test_mec_platform.py) (Mp1 필터, 같은 호스트 이동, 인스턴스 필터, 경계 통과).

## 한계

- 플랫폼은 ETSI 데이터 모델 일부를 구현한 `mec_mock`입니다. AMS 절차는 MEC 021(등록, `MobilityProcedureNotification`, `contextTransferState`)을 따르지만, 인스턴스 간 컨텍스트 형식은 EdgeGuard 자체 JSON입니다. MEC 021은 이 형식을 앱에 맡깁니다.
- Mp1은 플랫폼 OAuth 없이 동작합니다. 실제 MEC 플랫폼은 인스턴스화할 때 토큰을 발급합니다.
- 이 구독 경로들은 아직 ETSI MEC Sandbox에서 돌려 보지 않았습니다. 실제 플랫폼의 구역 이벤트 경로는 [`tools/mec_events_check.py`](../../tools/mec_events_check.py)로 점검합니다.
