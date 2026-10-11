# 대회 채점표 자체 평가 (공식 루브릭 기준)

[← README](../README.ko.md)

공식 루브릭(`Hackathon_Rubric_2026.pdf`)의 **17개 항목, 항목마다 0~5점(총 85점)** 기준으로, 업데이트할 때마다 갱신합니다.
Emerging 0~1 · Proficient 2~3 · Expert 4~5. 이전 기록(89/100)은 공개 전 가정한 5개 항목 기준이라 폐기했습니다.

## 현재 점수 — 2026-10-11 (v1.5)

| # | 항목 | 점수 | 근거 | 다음 단계 (목표 점수) |
|---|---|---|---|---|
| 1 | Innovative use of oneM2M | **5** | **group fanOutPoint**(구역 방송, 스웜 컨텍스트를 요청 한 번으로 읽기), **pollingChannel**(NAT 뒤 태그), announcement(핸드오버 시 IN-CSE에 AEAnnc), flexContainer · flexContainerInstance 이력, semanticDescriptor, accessControlObjectDetails, 라벨 탐색, MQTT 바인딩 | — |
| 2 | Communication protocols | **4** | 단말 → CSE는 **oneM2M MQTT 바인딩 over TLS**, 앱 ↔ CSE는 **HTTPS**(알림 포함), 단말 간 ESP-NOW(망 없이 동작하는 이유 설명), 에이전트는 MCP ([보안 전송](ko/transport-security.md)) | ESP32 펌웨어도 MQTT로 (→ 5) |
| 3 | Innovative scenarios | **5** | 여러 단말 → CSE → 여러 앱(MEC 앱 · AI 에이전트 · 연합학습 · 오케스트레이터 · 대시보드). 앱 로직 대신 oneM2M 기능(그룹 팬아웃 · 구독 · 탐색 · 시맨틱 · announcement)으로 경보 배포 · 등록 · 이동 · 스웜 조정 | — |
| 4 | Quality of Article | **4** | [hackster.io 게시](https://www.hackster.io/ahind012/edgeguard-stop-forklift-accidents-before-they-happen-e07309)(10/11, 영상 포함, [원고](hackster-article.md)): 개요 · H/W · 리소스 설계 · 프로토콜 · 그림 · 측정값 · oneM2M 장점 · ESTIMED 7절 | 회로도 · 팀원 추가 (→ 5) |
| 5 | Quality of Video | **3** | 최종 영상 [YouTube 게시](https://youtu.be/P2JI5ZG6PIg) · `results/edgeguard_final.mp4`(2분 34초, 자막): 문제 · 구조 · 라이브 데모 · 펌웨어 · 모빌리티 지도 · TR-0077 · 결과 | 내레이션 녹음, 실물 보드 장면 (→ 4) |
| 6 | Quality of Github | **4** | 영문 README · 빌드/실행 · CI가 핵심 데모 12종(SIL · SDT · 핸드오버 · 모빌리티 · 에이전트 · 연합학습 · 모델 전달 · 스웜 · 오케스트레이션 · 구역 방송 · 보안 전송 · 스택/ACL/HA)을 자동 검증. **공개 저장소**(10/11), 최종 영상 · 내레이션 대본 포함 | 기사 링크 반영 완료(10/11), About 설명 · 토픽 설정 |
| 7 | Promotion of oneM2M | 3 | README 'Why oneM2M' · 기능 표 · 표준 링크, ESTIMED/TR-0077 매핑 문서, 기사 초안이 oneM2M 장점 정리 | 기사 · 영상 게시 (→ 4~5) |
| 8 | Judge points | 0~1 | 공개 포럼 활동 미확인 | ACME 이슈(Content-Type, sqi=false 시맨틱 탐색 거부, MQTT 송신 요청 오류) 공개 보고 (팀) |
| 9 | Interview points | (본선) | 리소스 트리 · 장점 · 통합 방법 · TR-0077 7절 매핑 설명 가능 | 예상 Q&A |
| 10 | Security and Privacy | **4** | **TLS**(MQTT · HTTPS, 사이트 CA), 브로커 비밀번호 + 발신자별 ACL(다른 단말 사칭 차단), 디바이스 · 앱별 ACP, CREATE를 구독/CIN으로 한정(chty), 오케스트레이터가 재배치 시 권한 회수, 공격 6종 차단 CI 검증, 작업자 궤적은 현장에만, D2D HMAC | 단말별 인증서 · 키 순환 (→ 5) |
| 11 | Data Interoperability | **5** | SDT 데이터 모델(TS-0023 방식 자체 도메인 + 표준 cod:bat, MEC 데이터 · 호스트 · 배포 의도 · 모델 배포 클래스까지) + SAREF 시맨틱 쿼리, 라벨 탐색으로 자동 등록 | — |
| 12 | CSE Handover | **5** | 위치 · 가용성 · **MEC 네트워크(구역 이벤트)** 트리거, 상태 · 구독 · 보안 컨텍스트 복원, 서비스 중단 1.5~11 ms · 유실 0 측정 ([핸드오버](ko/handover.md), [모빌리티](ko/mobility.md)) | — |
| 13 | oneM2M–MEC App/VM Deployment | **4** | 배포 의도 리소스 하나 → 여러 MEC 호스트에 탐색 · 선택 · 배포 · 등록 · 프로비저닝, 호스트 장애 시 재배치 ([오케스트레이션](ko/orchestration.md)). 호스트 · 수명주기 API는 시뮬레이션 | ESTIMED VM / 컨테이너로 실제 배포 (→ 5) |
| 14 | Federated Learning (TR-0084) | **4~5** | 작업 · 참여자 · 라운드 · 모델 버전을 oneM2M 모델로, 동적 선택 · 이탈 · 늦은 참여, 데이터는 사이트에. **모델 전달**: 카나리 · 위험 엔진 활성화 · 섀도 감시 · 롤백 ([모델 전달](ko/swarm-and-model-delivery.md)) | ESTIMED VM에서 실행 (→ 5) |
| 15 | Geolocation Services | **4** | MEC 013 구역 이벤트(ENTERING/LEAVING) 구독 → oneM2M → 핸드오버 트리거, 위치 트윈(egs:ueLoc), 구역 그룹 지오펜싱 | 실제 ETSI Sandbox에서 구독 경로 실행 (→ 5) |
| 16 | MEC Services | **4** | **양방향** MEC–oneM2M(oneM2M 앱이 IPE로 MEC 요청), RNIS 단말별 신호 세기를 SDT(egs:rdLnk)로, 에이전트가 MEC MCP 서버로 소비 | Sandbox에서 RNIS 구독 실행 (→ 5) |
| 17 | AI Agents & MCP | **4~5** | MCP 서버 4개(IN · 구역 A · 구역 B · ETSI MEC) 오케스트레이션, 다단계 워크플로, 상태를 oneM2M에 저장, 서빙 CSE로 라우팅, 검증 · 오류 처리 ([AI 에이전트](ko/ai-agent.md)) | — |
| | **합계** | **약 62~65 / 85** (인터뷰 제외) | hackster 기사 게시(10/11) | **기사 · 영상 게시 · 포럼 활동까지 약 66~70** |

## 개발 계획

| 마일스톤 | 기간 | 내용 | 상태 |
|---|---|---|---|
| M1 | ~10/20 | 중간 보고서, flexContainer 데이터 모델 · 라벨 탐색 · SAREF | 완료 (10/11) |
| M3 일부 | ~11/10 | 구역 간 CSE 핸드오버 · 고장 전환 | 완료 (10/11) |
| M4 | ~11/17 | MCP 안전 에이전트, 연합학습 | 완료 (10/11) |
| M2 | 10/21~10/31 | group · pollingChannel, 단말 MQTT, TLS | 완료 (10/11) |
| M3 나머지 | 11/1~11/10 | MEC 위치 구역 이벤트 → 핸드오버 트리거, 양방향 MEC, 다중 호스트 오케스트레이션, 스웜, 모델 전달 | 완료 (10/11) |
| M5 | 11/10~11/20 | ESP32 실물 시연, 사용자 실험, hackster.io 게시, 최종 영상, 저장소 공개 | 예정 (팀) |

중간 보고서: [`submissions/EdgeGuard_Interim_Report.pptx`](submissions/EdgeGuard_Interim_Report.pptx) (10/20까지 팀 Discord 채널에 업로드)

## 갱신 기록

| 날짜 | 합계 | 변화 |
|---|---|---|
| 2026-10-11 | 23~24 / 85 | 공식 루브릭으로 재평가, 중간 보고서(.pptx) 작성 |
| 2026-10-11 | 24~25 / 85 | 발표 자료를 루브릭 항목별로 재구성(oneM2M 장점 · 기능 · 프로토콜 · 보안 · MEC 서비스 · 로드맵), README에 oneM2M 섹션 · 로드맵 추가(Promotion 2 → 3) |
| 2026-10-11 | 약 47~49 / 85 | 0점 항목 해결: SDT flexContainer · SAREF 데이터 모델(11: 0→5), CSE 핸드오버(12: 0→5), 연합학습(14: 0→4), MCP 에이전트(17: 0→4~5), hackster 기사 초안(4: 게시 시 4), announcement 사용(1: 2→4), 시나리오(3: 3→4) |
| 2026-10-11 | 약 56~59 / 85 | ESTIMED/TR-0077 7절 반영: 구역 방송(group · pollingChannel, 1: 4→5), MQTT/TLS · HTTPS(2: 2→4, 10: 3→4), 스웜 · 오케스트레이션 시나리오(3: 4→5), 다중 호스트 오케스트레이션(13: 3→4), 모델 전달(14: 4→4~5), MEC 구역 이벤트 · 네트워크 트리거 핸드오버(15: 2→4), 양방향 MEC · RNIS SDT(16: 3→4), 모빌리티 지도 · 매핑 문서 |
| 2026-10-11 | 약 58~61 / 85 | 저장소 공개(6: 3→4), 최종 영상 · 자막 · 내레이션 대본(5: 2→3), hackster · 포럼 게시 준비([publish-checklist.md](publish-checklist.md)) |
| 2026-10-11 | 약 58~61 / 85 | 최종 영상 YouTube 게시(https://youtu.be/P2JI5ZG6PIg); README · 기사 · 체크리스트에 링크 반영 |
| 2026-10-11 | 약 62~65 / 85 | hackster.io 기사 게시(https://www.hackster.io/ahind012/edgeguard-stop-forklift-accidents-before-they-happen-e07309, 4: 게시 시 4 → 4); README · 기사 · 체크리스트 · 포럼 초안에 링크, 저장소 About 설명 · 토픽 |
