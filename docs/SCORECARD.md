# 대회 채점표 자체 평가 (공식 루브릭 기준)

[← README](../README.ko.md)

공식 루브릭(`Hackathon_Rubric_2026.pdf`)의 **17개 항목, 항목마다 0~5점(총 85점)** 기준으로, 업데이트할 때마다 갱신합니다.
Emerging 0~1 · Proficient 2~3 · Expert 4~5. 이전 기록(89/100)은 공개 전 가정한 5개 항목 기준이라 폐기했습니다.

## 현재 점수 — 2026-10-11

| # | 항목 | 점수 | 근거 | 다음 단계 (목표 점수) |
|---|---|---|---|---|
| 1 | Innovative use of oneM2M | 2 | AE · CNT · SUB · ACP + maxNrOfInstances(nearmiss 2000 등) | group 경보 팬아웃, pollingChannel, announcement (M2 → 4) |
| 2 | Communication protocols | 1 | 단말 · 앱 모두 HTTP로 CSE 접속 (D2D는 ESP-NOW) | 단말 MQTT · 앱 HTTP, 이유 설명 (M2 → 4) |
| 3 | Innovative scenarios | 3 | 센서+액추에이터 여러 단말 → CSE → 여러 앱(MEC 앱 · 대시보드 · 클라우드), 구독/알림 허브 | oneM2M 기능(group · announcement)으로 앱 로직 대체 (M2 → 4) |
| 4 | Quality of Article | 0 | hackster.io 기사 없음 | 기사 작성 (M5 → 4) |
| 5 | Quality of Video | 2 | 데모 영상 2편(라이브 데모, 펌웨어 + 휴대폰) | 최종 영상: 실물 보드 · 스토리 (M5 → 4) |
| 6 | Quality of Github | 3 | 영문 README · 빌드/배포 문서 · CI. **저장소 비공개**, 기사 링크 없음 | 공개 전환 + 기사 링크 (M5 → 5) |
| 7 | Promotion of oneM2M | 3 | README에 'Why oneM2M' · 사용 기능 표 · oneM2M 표준 · ACME · Mobius 링크, 발표 자료에 oneM2M 장점 슬라이드 | 기사 · 영상에서 oneM2M 추천 (M5 → 4~5) |
| 8 | Judge points | 0~1 | 공개 포럼 활동 미확인 | ACME 이슈(Content-Type) 공개 보고, Discord 질의 (팀) |
| 9 | Interview points | (본선) | 리소스 트리 · 장점 설명 가능 | 통합 방법론 · 선택 이유 Q&A 준비 |
| 10 | Security and Privacy | 3 | 디바이스별 ACP · 최소 권한, CI 위조 쓰기 403 검증, D2D HMAC | TLS + ACP (M2 → 4~5) |
| 11 | Data Interoperability | 0 | contentInstance JSON(독자 모델), 라벨 미사용 | FlexContainer + 라벨 + 탐색(M1 → 3), SDT/SAREF 검토 |
| 12 | CSE Handover | 0 | 미구현 | 구역별 MN-CSE 간 지게차 AE 핸드오버, 중단 시간 측정 (M3 → 4) |
| 13 | oneM2M–MEC App/VM Deployment | 3 | AdvantEDGE 자체 창고 시나리오 배포, 절차 문서화 | 여러 MEC 호스트 오케스트레이션 (M3 → 4) |
| 14 | Federated Learning (TR-0084) | 0 | 미구현 | 궤적 예측 모델 FL (M4, 선택) |
| 15 | Geolocation Services | 2 | MEC Location → MEC-IPE → oneM2M → 앱 | 위치 구역 이벤트 · 지오펜싱 (M3 → 4) |
| 16 | MEC Services | 2 | RNIS(위치 외 MEC 서비스)를 oneM2M으로 사용 | 양방향 MEC–oneM2M (M3 → 4) |
| 17 | AI Agents & MCP | 0 | 미구현 | oneM2M MCP 서버 + 안전관리 에이전트 (M4 → 3~4) |
| | **합계** | **24~25 / 85** (인터뷰 제외 80점 중) | | **계획 완료 시 약 60** |

## 개발 계획 (중간 보고서와 동일)

| 마일스톤 | 기간 | 내용 |
|---|---|---|
| M1 | ~10/20 | 중간 보고서 제출, FlexContainer 데이터 모델 · 라벨 기반 탐색 |
| M2 | 10/21~10/31 | group · pollingChannel · announcement, 단말 MQTT, TLS |
| M3 | 11/1~11/10 | MEC 구역 간 CSE 핸드오버, 지오펜싱, 다중 호스트 배포 |
| M4 | 11/11~11/17 | MCP 안전관리 에이전트, (선택) 연합학습 |
| M5 | 11/10~11/20 | ESP32 실물 시연, 사용자 실험, hackster.io 기사, 최종 영상, 저장소 공개 |

중간 보고서: [`submissions/EdgeGuard_Interim_Report.pptx`](submissions/EdgeGuard_Interim_Report.pptx) (10/20까지 팀 Discord 채널에 업로드)

## 갱신 기록

| 날짜 | 합계 | 변화 |
|---|---|---|
| 2026-10-11 | 23~24 / 85 | 공식 루브릭으로 재평가, 중간 보고서(.pptx) 작성 |
| 2026-10-11 | 24~25 / 85 | 발표 자료를 루브릭 항목별로 재구성(oneM2M 장점 · 기능 · 프로토콜 · 보안 · MEC 서비스 · 로드맵), README에 oneM2M 섹션 · 로드맵 추가(Promotion 2 → 3) |
