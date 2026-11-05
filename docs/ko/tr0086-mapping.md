# EdgeGuard와 TR-0086 개발자 가이드

[← README](../../README.ko.md) · [English](../tr0086-mapping.md) · [ESTIMED / TR-0077 대응](estimed-mapping.md)

TR-0086 개발자 가이드(oneM2M + ETSI MEC 배치, 2026년 10월 말 해커톤 팀에 공유)는 함께 배치한 플랫폼을 단계별로 안내합니다. 배치 옵션 선택, 플랫폼 기동(5.2), 단말 등록(5.3), AE를 MEC 앱으로 실행(5.4), 선택 과제로 핸드오버(5.5)와 위치 인식 단말(5.6), 부록 A의 oneM2M 기본 요소입니다. EdgeGuard는 가이드 공개 전에 만들었고, 이 문서는 각 단계를 EdgeGuard가 어디서 하는지, CI에서 무엇을 확인하는지 연결합니다.

## 배치 옵션(5.2.2): 구역마다 C

| 옵션 | 가이드 | EdgeGuard |
|---|---|---|
| A | MEC-IPE를 MEC 앱으로, 클라우드 IN-CSE에 직접 등록 | 클라우드 계층: 홈 기록, announcement, 연합학습 조정, 오케스트레이터, AI 에이전트 |
| B | 별도 엣지 노드의 MN-CSE + MEC-IPE | 이것도 동작: MEC 앱이 다른 노드의 CSE에 그대로 붙음(`sil.yaml`, ETSI Sandbox 실행) |
| **C** | **MEC 호스트에 MN-CSE를 MEC 앱으로 함께 배치** | **채택**: 구역마다 MEC 호스트가 구역 MN-CSE(ACME), EdgeGuard MEC 앱, MEC-IPE를 실행 |
| D | MN-CSE를 MEC 서비스로 | 사용 안 함 |

**왜 C인가:** 충돌 경보에 쓸 수 있는 시간은 1~3초입니다. CSE · 판단 · MEC 데이터가 한 호스트에 있으면 경보 지연 중앙값이 25 ms(클라우드만 85 ms)이고, 작업자 궤적이 구역 밖으로 나가지 않으며, 클라우드 연결이 끊겨도 구역이 혼자 동작합니다.

**실행 환경(5.2.4.2):** 로컬 MEC Sandbox(STF_685 브랜치)는 설치하지 않았습니다. MN-CSE는 직접 띄운 ACME(가이드의 "your own MN-CSE" 경로)이고, MEC 013 / 012 / 011 / 021은 AdvantEDGE 방식 시나리오를 재생하는 `mec_mock`이 제공합니다. 폴링 경로는 공개 ETSI MEC Sandbox에서도 실행했습니다([mec-sandbox.md](mec-sandbox.md)).

## 단계별

| TR-0086 | 가이드가 요구하는 것 | EdgeGuard | 확인 |
|---|---|---|---|
| **5.2** 플랫폼 기동 | IN-CSE 기동, MEC 플랫폼 · MEC 011 API 확인, MN-CSE / MEC-IPE 기동과 등록 | `scripts/acme.sh start in mn-a mn-b`: IN-CSE + 구역 MN-CSE 2개, 각 MN-CSE가 Mcc로 등록(`scripts/acme-mn-*.ini`의 `registrarCse*`). MEC 011 Mp1 서비스 등록 · 탐색([mec-platform.md](../mec-platform.md)) | 매 커밋 CI, `mec_platform_demo.py` 10/10 |
| **5.3** 단말 등록 | 옵션의 CSE에 단말 / AE 등록, 데이터 게시 | 태그와 지게차 모듈이 각자 AE + ACP 등록, 데이터는 SDT flexContainer 트윈(`egs:wrkTg`, `egs:frkMe`) 또는 contentInstance, 라벨 탐색으로 단말 목록 없이 자동 등록([data-model.md](data-model.md)) | CI에서 약 9초 등록, Mobius 접근 검사 8/8, 원본 ESP32 펌웨어가 HTTP · MQTT · 상호 TLS로 통과 |
| **5.4** AE를 MEC 앱으로 | AE를 관리되는 MEC 앱으로 패키징 · 실행 | MEC 앱은 컨테이너(`deploy/edge-app`), oneM2M 배치 의도 리소스 하나로 호스트 탐색 → 선택 → 배포 → Mp1 등록 → 단말 ACP → 감시 → 호스트 장애 시 재배치([orchestration.md](../orchestration.md)) | `orchestration_demo.py` 11/11, 약 2~3초에 재배치 |
| **5.5** 핸드오버 *(선택)* | 연속성을 잃지 않고 단말을 MN-CSE 사이에서 이동(MEC 012 RNIS) | 상태 · ACP · 이동형 구독 · announcement · 홈 기록을 옮기는 make-before-break, 트리거는 MEC 013 구역 이벤트, RNIS 신호 세기(`egs:rdLnk`의 RSRP / RSRQ), MEC 021 AMS([handover.md](handover.md), [mobility.md](mobility.md)) | `handover_demo.py` 10/10 + 8/8, 구역 이벤트 핸드오버 1.5~8 ms, 유실 0 |
| **5.6** 위치 인식 단말 *(선택)* | 네트워크 위치(MEC 013) 또는 단말 위치 | 둘 다: MEC 013 위치와 구역 · 영역 · 거리 이벤트를 oneM2M 리소스로(`egs:ueLoc`, `MEC-IPE/geoEvents`), 단말 자체 UWB 위치는 트윈에 | `mobility_demo.py` 10/10, 지오펜스 · 거리 이벤트 → oneM2M 약 10 ms |

## 부록 A 기본 요소

| 기본 요소 | EdgeGuard |
|---|---|
| 컨테이너 | 단말 데이터, 경보, 아차사고(`maxNrOfInstances`로 이력 제한) |
| ACP | 단말 AE마다 하나, MEC 앱은 트윈에 구독만 생성 가능(`chty`) |
| 구독 | 위치 → MEC 앱, 경보 → 태그 · 지게차 모듈, MEC 이벤트 → 앱 |
| 그룹 | 구역마다 하나: DANGER 경보는 `<group>/fopt` 요청 한 번, 지게차 스웜 계획 |
| 데이터 게시 | 위치 최대 10 Hz(근처에 아무도 없으면 2 Hz) |
| 최신값 조회 | `<container>/la`([`edgeguard/onem2m.py`](../../edgeguard/onem2m.py)) |
| 하향 명령 | 태그에 WAIT / STEP ASIDE / GO, 지게차 모듈에 속도 계획 · 정지 지점, 각각 단말의 `status` 컨테이너로 확인 |

## 가이드 너머

가이드가 단계별로 다루지 않는 TR-0077 7절 항목도 모두 CI에서 실행합니다. oneM2M 위 연합학습(TR-0084)과 모델 전달 · 롤백, 지게차 스웜(7.4), MEC 021 앱 이동성, MCP 기반 AI 에이전트([estimed-mapping.md](estimed-mapping.md)).
