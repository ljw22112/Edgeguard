# ETSI MEC를 통한 모빌리티: 구역 이벤트, 신호 세기, 네트워크 트리거 핸드오버

[← README](../../README.ko.md) · [English](../mobility.md) · [TR-0077 매핑](estimed-mapping.md)

폴링 MEC-IPE([`tools/mec_ipe.py`](../../tools/mec_ipe.py))는 UE 위치를 CSE로 복사합니다. 이벤트 기반 MEC-IPE([`edgeguard/mobility.py`](../../edgeguard/mobility.py))는 양방향으로 동작합니다.

**MEC → oneM2M.** MEC 013 구역/사용자 위치 이벤트와 MEC 012 MeasRepUe 보고를 구독하고, 일어나는 즉시 oneM2M에 기록합니다.
- 구역 이벤트는 `MEC-IPE/zoneEvents`의 `contentInstance`가 됨
- UE별 위치와 무선 링크는 이력을 남기는 SDT flexContainer에 저장

**oneM2M → MEC.** oneM2M 앱이 `MEC-IPE/requests`에 `contentInstance`를 만듭니다.
- `zone_subscribe`
- `radio_subscribe`
- `location`
- `unsubscribe`

IPE가 MEC API를 호출하고, 같은 `rqi`로 `MEC-IPE/responses`에 답합니다. 앱은 MEC API를 직접 다루지 않고 MEC 자격증명도 없이 MEC 서비스를 씁니다.

```
MEC-IPE                    AE (IN-CSE)
  requests                 CNT        읽기 권한자는 contentInstance 생성만 가능 (chty 4)
  responses                CNT        읽기/구독
  zoneEvents               CNT        {ue, zone, event ENTERING/LEAVING, poa, mec_ts, ipe_ts}
  ue_<address>             egs:mecUe  lbl egs:mec/ue, egs:id/<address>
    location               egs:ueLoc  위도, 경도, 정확도, zoneId, accessPointId, 시각 (mni 50)
    radio                  egs:rdLnk  서빙 셀, RSRP, RSRQ, 인접 셀, 인접 RSRP, 시각 (mni 100)
```

RSRP와 RSRQ는 3GPP TS 36.133 보고 인덱스입니다(dBm = 인덱스 − 141).

## 네트워크 트리거 핸드오버

`trigger="network"`로 만든 `HandoverClient`는 자기 위치를 무시하고 MEC 플랫폼을 따릅니다.
1. MEC 플랫폼이 "forklift_01 ENTERING_AREA_EVENT zoneB"를 보고합니다.
2. MEC-IPE가 이를 `MEC-IPE/zoneEvents`에 기록합니다.
3. 그 컨테이너를 구독한 디바이스가 `network_trigger("B")`를 호출합니다.
4. 구역 B의 MN-CSE에 트윈을 백그라운드로 준비하고 다음 샘플에서 전환합니다. 절차는 [위치 핸드오버](handover.md)와 같은 make-before-break입니다.

ESTIMED가 말하는 트리거 주체 "MEC 네트워크 또는 무선 시스템"입니다.

## 데모와 측정 (매 커밋 CI)

```bash
scripts/acme.sh start in mn-a mn-b
python tools/mobility_demo.py       # 10개 검사 -> results/mobility.json
python tools/mobility_map.py        # docs/img/mobility_map.html (+ .png)
```

시나리오는 [`scenarios/edgeguard-two-zones.yaml`](../../scenarios/edgeguard-two-zones.yaml)이고 AdvantEDGE 형식입니다.
- 구역 두 개, 구역마다 5G 스몰셀 하나와 MN-CSE 하나
- forklift_01이 4 m/s로 A → B → A 주행

`mec_mock`이 0.25 s GIS 주기로 재생하면서 구역 변경을 감지하고 알림을 보냅니다. RSRP는 로그 거리 경로손실 모델(1 m에서 −44 dBm, 지수 3.5)입니다.

| | CI 실행 |
|---|---|
| 핸드오버 | A → B, 이어서 B → A, 둘 다 네트워크가 트리거 |
| 서비스 중단 | 핸드오버당 1.5–8 ms |
| 손실 샘플 | 0 |
| MEC 구역 이벤트 → oneM2M contentInstance | 중앙값 15–45 ms |
| oneM2M을 통한 MEC 요청(구독) | 왕복 ≈ 20 ms |
| 핸드오버 시점 무선 상태 | 새 셀이 이전 셀 이상으로 강하게 수신됨(경계에서 각각 ≈ −90 dBm) |

**검사:**
- oneM2M을 통한 구역 구독(MEC 구독 2개)
- oneM2M을 통한 위치 조회
- oneM2M에 ENTERING zoneB, 이어서 zoneA 기록
- 네트워크가 트리거한 A → B → A 핸드오버
- 손실 0
- 중단 300 ms 미만
- `egs:rdLnk`의 서빙 셀이 cellA → cellB → cellA
- 핸드오버마다 새 셀이 이전 셀 이상으로 강함
- 레이블로 MEC 트윈 탐색
- oneM2M으로 MEC 구독 해제

![모빌리티 지도](../img/mobility_map.png)

지도(시간 슬라이더가 있는 HTML)는 평면도 위의 지게차, 서비스 중인 CSE, 마지막 MEC 구역 이벤트, 두 셀의 RSRP, 핸드오버를 보여 줍니다. 그 아래 RSRP 그래프에서 구역 경계의 신호 교차를 볼 수 있습니다.
