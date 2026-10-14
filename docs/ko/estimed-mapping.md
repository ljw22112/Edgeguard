# EdgeGuard와 ESTIMED (TR-0077 7절)

[← README](../../README.ko.md) · [English](../estimed-mapping.md)

ETSI STF 685 **ESTIMED**는 oneM2M과 ETSI MEC를 통합해, 표준 IoT 서비스를 MEC 엣지 환경에서 배포하고 오케스트레이션하고 사용할 수 있게 하는 프로젝트입니다. oneM2M TR-0077 7절이 다룰 공백을 정리하고, ESTIMED PoC(TDE-2026-0052)가 이를 시연합니다. EdgeGuard는 그 PoC 루프 **감지 → 조정 → 학습 → 배포 → 개선**의 창고 버전입니다. 아래 기능은 모두 매 커밋 CI에서 ACME CSE 위에서 실행됩니다.

## 배포 연속체: 구역마다 옵션 C, 클라우드에 IN-CSE

ESTIMED는 oneM2M과 MEC의 결합 방식 네 가지를 인정합니다.
- **A**: 클라우드 oneM2M + 엣지 MEC
- **B**: 별도 엣지 노드
- **C**: 같은 물리 엣지 노드
- **D**: 깊은 통합

EdgeGuard는 구역마다 **옵션 C**입니다. 각 구역의 MEC 호스트가 다음을 함께 실행합니다.
- 구역 **MN-CSE**
- EdgeGuard MEC 앱
- MEC-IPE

클라우드나 사이트 데이터센터의 **IN-CSE**는 전역 컨텍스트, 홈 레코드, 공지(announcement)를 맡습니다. 이 계층이 옵션 A에 해당합니다. MEC 앱은 다른 노드의 CSE에도 그대로 동작하므로 옵션 B도 지원합니다(`sil.yaml`, ETSI Sandbox 구성).

## TR-0077 7절 → EdgeGuard

| 절 | ESTIMED 기능 | EdgeGuard | 코드 · 데모 (CI) |
|---|---|---|---|
| **7.1 연동** | oneM2M 안의 MEC 위치 서비스, MEC API용 SDT 모델 | 이벤트 기반 양방향 MEC-IPE: MEC 013 구역 이벤트는 `contentInstance`로, MEC 012 MeasRepUe와 MEC 013 위치는 SDT 트윈(`egs:mecUe`, `egs:ueLoc`, `egs:rdLnk`)으로 기록. oneM2M 앱은 `<MEC-IPE>/requests`로 MEC 서비스를 요청 | [`mobility.py`](../../edgeguard/mobility.py) · `mobility_demo.py` 10/10 |
| 7.1 | oneM2M 앱을 위한 MEC 플랫폼 서비스 | **MEC 011 Mp1**: 인스턴스가 CSE · AE 위치를 담아 `edgeguard-safety`를 등록하고 Location 서비스를 Mp1로 탐색. **MEC 013 영역 · 거리** 구독을 oneM2M에서 요청, 이벤트는 `MEC-IPE/geoEvents` | [`mec_platform.py`](../../edgeguard/mec_platform.py) · `mec_platform_demo.py` 10/10 ([MEC 플랫폼](mec-platform.md)) |
| 7.1 | MEC 앱 오케스트레이션: 탐색 → 선택 → 배포 → 등록 → 프로비저닝 | 호스트가 스스로 등록(`egs:mecHs`)하고, 운영자는 `egs:depIn` 의도 하나만 생성. 오케스트레이터가 배치하고, 호스트 수명주기 API로 배포하고, 등록을 기다린 뒤 디바이스 ACP를 부여하고, 설정하고, 감시하다가 호스트가 죽으면 다시 배치 | [`orchestration.py`](../../edgeguard/orchestration.py) · `orchestration_demo.py` 11/11 |
| **7.2 핸드오버** | 연속성 번들: AE 식별·등록, 핸드오버 상태, 서비스 중인 MN-CSE 확인. 트리거 주체: MEC 네트워크/무선 시스템 | make-before-break 트윈 이전(상태, ACP, 이동 가능한 구독, 공지, 홈 레코드). 트리거: 디바이스 위치, CSE 가용성, **MEC 네트워크**(구역 이벤트), **MEC 021 AMS**(앱 인스턴스 간 컨텍스트 전송을 동반한 이동) | [`handover.py`](../../edgeguard/handover.py) · `handover_demo.py` 10/10 + 8/8, `mobility_demo.py`, `mec_platform_demo.py` |
| **7.3 연합학습** | 탐색, 선택, 학습, 집계, 추론. 모델 계보, 활성화, 롤백("집계 ≠ 운영 모델 전달") | oneM2M 위의 TR-0084 역할: 레이블로 참가자 탐색, 이탈과 늦은 참여, FedAvg. 이어서 **전달**: 사이트 보유 데이터로 카나리 평가, 위험 엔진(`guidance_fl`)에서 활성화, 섀도 감시, 롤백. 상태는 `egs:mdlDp`에 기록 | [`fl.py`](../../edgeguard/fl.py), [`model_delivery.py`](../../edgeguard/model_delivery.py) · 8/8, 8/8. **오케스트레이터가 클라이언트를 배포**: [`fl_app.py`](../../edgeguard/fl_app.py) · `fl_deploy_demo.py` 9/9(의도 → 배포 → 탐색 → 학습 → 집계 → 추론, 호스트 장애, 늦은 참여, 컨테이너) |
| **7.4 스웜 컴퓨팅** | 멤버십, 컨텍스트, 조정, 권고. 참여자가 로컬 권한을 유지 | 계획 컨테이너의 `<group>`이 멤버십. 팬아웃 요청 한 번으로 공유 컨텍스트를 읽음. 각 지게차가 코디네이터 없이 같은 충돌 없는 일정을 직접 계산 | [`swarm.py`](../../edgeguard/swarm.py) · `swarm_demo.py` 9/9 |
| 보조 | 그룹 통신, NAT 뒤 디바이스 | `<group>/fopt`로 구역 방송, `<pollingChannel>`로 수신 | [`zones.py`](../../edgeguard/zones.py) · 9/9 |
| 보조 | 보안 전송 | 디바이스는 oneM2M MQTT 바인딩 over TLS(브로커 비밀번호, 발신자별 ACL), CSE와 앱은 HTTPS | [`mqtt_binding.py`](../../edgeguard/mqtt_binding.py) · 10/10 |
| 보조 | 통합 시스템 위의 AI | MCP 서버 위의 근무조 안전 에이전트: oneM2M IN + 구역 MN-CSE, ETSI MEC | [`agent/`](../../agent) · 9/9 |

## PoC의 모빌리티 슬라이드 (창고판)

PoC는 지도 위 이동, 핸드오버, 그리고 다른 MEC 서비스(신호 세기)를 보여 주는 슬라이드를 요청합니다. [`docs/img/mobility_map.html`](../img/mobility_map.html)이 실제 실행(`tools/mobility_demo.py` → `tools/mobility_map.py`)에서 만든 그 화면입니다.
- 지게차가 구역 A → B → A로 이동
- MEC 플랫폼이 구역 변경을 감지하고, MEC-IPE가 이를 oneM2M에 기록
- 지게차 트윈이 그 구역의 MN-CSE로 이동
- 경계를 넘을 때 두 셀의 RSRP가 교차하는 모습

![모빌리티 지도](../img/mobility_map.png)

## 아직 대체물인 부분

- 이 MEC 플랫폼은 `mec_mock`입니다. EdgeGuard가 쓰는 MEC 013/012 데이터 모델과 구독을 제공하고 AdvantEDGE 시나리오를 재생합니다. 폴링 경로는 ETSI MEC Sandbox에서 검증했지만, 구독 경로는 아직 Sandbox에서 돌려 보지 않았습니다.
- MEC 호스트 수명주기: 시뮬레이션 호스트 위의 단순화한 MEC 010-2 방식 API(생성, 조회, 종료)입니다. 배포된 인스턴스는 실제로 등록되고 프로비저닝되어 실시간 데이터를 처리하는 oneM2M 앱이며, 인스턴스마다 컨테이너 하나로 실행됩니다(`--runtime docker`).
- MQTT로 등록한 AE로의 알림: 현재 ACME MQTT 바인딩은 CSE가 MQTT로 요청을 보낼 때 실패하므로, 앱은 HTTPS로 알림을 받습니다.
