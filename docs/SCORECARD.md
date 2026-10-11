# 대회 채점표 자체 평가 (공식 루브릭 기준)

[← README](../README.ko.md)

공식 루브릭(`Hackathon_Rubric_2026.pdf`)의 **17개 항목, 항목마다 0~5점(총 85점)** 기준으로, 업데이트할 때마다 갱신합니다.
Emerging 0~1 · Proficient 2~3 · Expert 4~5. 이전 기록(89/100)은 공개 전 가정한 5개 항목 기준이라 폐기했습니다.

## 현재 점수 — 2026-10-11 (v1.4)

| # | 항목 | 점수 | 근거 | 다음 단계 (목표 점수) |
|---|---|---|---|---|
| 1 | Innovative use of oneM2M | **4** | **announcement**(핸드오버 시 IN-CSE에 AEAnnc), flexContainer · flexContainerInstance 이력, semanticDescriptor, accessControlObjectDetails, maxNrOfInstances, 라벨 탐색 | group 경보 팬아웃, pollingChannel (10/31 → 5) |
| 2 | Communication protocols | 2 | 단말 · 앱 → CSE는 HTTP, 단말 간 ESP-NOW(망 없이 동작하는 이유 설명), 에이전트는 MCP | 단말 MQTT · 앱 HTTP (10/31 → 4) |
| 3 | Innovative scenarios | **4** | 여러 단말 → CSE → 여러 앱(MEC 앱 · AI 에이전트 · 연합학습 · 대시보드), 앱 로직 대신 oneM2M 기능(구독 · 탐색 · 시맨틱 · announcement)으로 등록 · 이동 처리 | group으로 경보 배포 (→ 5) |
| 4 | Quality of Article | 0 → **4 (게시 시)** | [hackster.io 기사 초안](hackster-article.md) 완료: 개요 · H/W · 리소스 설계 · 프로토콜 · 그림 · 측정값 · oneM2M 장점 | 팀이 hackster.io에 게시 (영상 링크 포함) |
| 5 | Quality of Video | 2 | 데모 영상 2편 | 최종 영상: 실물 보드 · 핸드오버 · 에이전트 (11/20 → 4) |
| 6 | Quality of Github | 3 | 영문 README · 빌드/실행 · CI가 모든 데모 자동 검증. **비공개**, 기사 링크 없음 | 공개 전환 + 기사 링크 (→ 5) |
| 7 | Promotion of oneM2M | 3 | README 'Why oneM2M' · 기능 표 · 표준 링크, 기사 초안이 oneM2M 장점 정리 | 기사 · 영상 게시 (→ 4~5) |
| 8 | Judge points | 0~1 | 공개 포럼 활동 미확인 | ACME 이슈(Content-Type, sqi=false 시맨틱 탐색 거부) 공개 보고 (팀) |
| 9 | Interview points | (본선) | 리소스 트리 · 장점 · 통합 방법 설명 가능 | 예상 Q&A |
| 10 | Security and Privacy | 3 | 디바이스 · 앱별 ACP, CREATE를 구독으로 한정(chty), 위조 쓰기 403 CI 검증, 위치 데이터는 현장 CSE에만, D2D HMAC | TLS + ACP (10/31 → 4~5) |
| 11 | Data Interoperability | **5** | **SDT 데이터 모델(TS-0023 방식 자체 도메인 + 표준 cod:bat) + SAREF 시맨틱 쿼리**, 라벨 탐색으로 자동 등록 ([데이터 모델](ko/data-model.md)) | — |
| 12 | CSE Handover | **5** | 위치 · 가용성 기반 자동 핸드오버, 상태 · 구독 · 보안 컨텍스트 복원, 서비스 중단(3~9 ms) · 유실(0) 측정 ([핸드오버](ko/handover.md)) | — |
| 13 | oneM2M–MEC App/VM Deployment | 3 | AdvantEDGE 자체 창고 시나리오, 구역별 MEC 호스트(MN-CSE) 구성 문서화 | 여러 호스트 오케스트레이션 (11/10 → 4) |
| 14 | Federated Learning (TR-0084) | **4** | 작업 · 참여자 · 라운드 · 모델 버전을 oneM2M 모델로, 동적 선택 · 이탈 · 늦은 참여, 데이터는 사이트에 ([연합학습](ko/federated-learning.md)) | ESTIMED VM에서 실행 (→ 5) |
| 15 | Geolocation Services | 2 | MEC Location → MEC-IPE → oneM2M → 앱 | 위치 구역 이벤트로 지오펜싱 · 핸드오버 트리거 (11/10 → 4) |
| 16 | MEC Services | 3 | RNIS(위치 외 MEC 서비스)를 oneM2M으로 사용, 에이전트가 MEC MCP 서버로 소비 | 양방향 MEC–oneM2M (→ 4) |
| 17 | AI Agents & MCP | **4~5** | MCP 서버 4개(IN · 구역 A · 구역 B · ETSI MEC) 오케스트레이션, 다단계 워크플로, 상태를 oneM2M에 저장, 서빙 CSE로 라우팅, 검증 · 오류 처리 ([AI 에이전트](ko/ai-agent.md)) | — |
| | **합계** | **약 47~49 / 85** (인터뷰 제외) | 기사 게시 시 약 52~54 | **로드맵 완료 시 약 65** |

## 개발 계획

| 마일스톤 | 기간 | 내용 | 상태 |
|---|---|---|---|
| M1 | ~10/20 | 중간 보고서, flexContainer 데이터 모델 · 라벨 탐색 · SAREF | 완료 (10/11) |
| M3 일부 | ~11/10 | 구역 간 CSE 핸드오버 · 고장 전환 | 완료 (10/11) |
| M4 | ~11/17 | MCP 안전 에이전트, 연합학습 | 완료 (10/11) |
| M2 | 10/21~10/31 | group · pollingChannel, 단말 MQTT, TLS | 예정 |
| M3 나머지 | 11/1~11/10 | MEC 위치 구역 이벤트 → 지오펜싱 · 핸드오버 트리거, 양방향 MEC, 다중 호스트 | 예정 |
| M5 | 11/10~11/20 | ESP32 실물 시연, 사용자 실험, hackster.io 게시, 최종 영상, 저장소 공개 | 예정 (팀) |

중간 보고서: [`submissions/EdgeGuard_Interim_Report.pptx`](submissions/EdgeGuard_Interim_Report.pptx) (10/20까지 팀 Discord 채널에 업로드)

## 갱신 기록

| 날짜 | 합계 | 변화 |
|---|---|---|
| 2026-10-11 | 23~24 / 85 | 공식 루브릭으로 재평가, 중간 보고서(.pptx) 작성 |
| 2026-10-11 | 24~25 / 85 | 발표 자료를 루브릭 항목별로 재구성(oneM2M 장점 · 기능 · 프로토콜 · 보안 · MEC 서비스 · 로드맵), README에 oneM2M 섹션 · 로드맵 추가(Promotion 2 → 3) |
| 2026-10-11 | 약 47~49 / 85 | 0점 항목 해결: SDT flexContainer · SAREF 데이터 모델(11: 0→5), CSE 핸드오버(12: 0→5), 연합학습(14: 0→4), MCP 에이전트(17: 0→4~5), hackster 기사 초안(4: 게시 시 4), announcement 사용(1: 2→4), 시나리오(3: 3→4) |
