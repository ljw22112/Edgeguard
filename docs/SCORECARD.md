# 대회 채점표 자체 평가 (공식 루브릭 기준)

[← README](../README.ko.md)

공식 루브릭(`Hackathon_Rubric_2026.pdf`)의 **17개 항목, 항목마다 0~5점(총 85점)** 기준으로, 업데이트할 때마다 갱신합니다.
Emerging 0~1 · Proficient 2~3 · Expert 4~5. 이전 기록(89/100)은 공개 전 가정한 5개 항목 기준이라 폐기했습니다.

## 현재 점수 — 2026-10-14 (v1.5)

| # | 항목 | 점수 | 근거 | 다음 단계 (목표 점수) |
|---|---|---|---|---|
| 1 | Innovative use of oneM2M | **5** | **group fanOutPoint**(구역 방송, 스웜 컨텍스트를 요청 한 번으로 읽기), **pollingChannel**(NAT 뒤 태그), announcement(핸드오버 시 IN-CSE에 AEAnnc), flexContainer · flexContainerInstance 이력, semanticDescriptor, accessControlObjectDetails, 라벨 탐색, MQTT 바인딩 | — |
| 2 | Communication protocols | **5** | 단말 ↔ CSE: **펌웨어까지 oneM2M MQTT 바인딩 over TLS, CSE → 단말 경보도 MQTT 알림**(p50 약 10 ms)(`M2M_MQTT=1`, 단말 인증서로 상호 TLS 가능, CI에서 원본 펌웨어로 검증), 앱 ↔ CSE: **HTTPS**(알림 포함), NAT 뒤 태그: pollingChannel, 단말 간: ESP-NOW(망 없이 동작), 에이전트: MCP ([보안 전송](ko/transport-security.md)) | — |
| 3 | Innovative scenarios | **5** | 여러 단말 → CSE → 여러 앱(MEC 앱 · AI 에이전트 · 연합학습 · 오케스트레이터 · 대시보드). 앱 로직 대신 oneM2M 기능(그룹 팬아웃 · 구독 · 탐색 · 시맨틱 · announcement)으로 경보 배포 · 등록 · 이동 · 스웜 조정 | — |
| 4 | Quality of Article | **4** | [hackster.io 게시](https://www.hackster.io/ahind012/edgeguard-stop-forklift-accidents-before-they-happen-e07309)(10/11, 영상 포함, [원고](hackster-article.md)): 개요 · H/W · 리소스 설계 · 프로토콜 · 그림 · 측정값 · oneM2M 장점 · ESTIMED 7절 | 회로도 · 팀원 추가 (→ 5) |
| 5 | Quality of Video | **3** | 최종 영상 [YouTube 게시](https://youtu.be/P2JI5ZG6PIg) · `results/edgeguard_final.mp4`(2분 34초, 자막): 문제 · 구조 · 라이브 데모 · 펌웨어 · 모빌리티 지도 · TR-0077 · 결과 | 내레이션 녹음, 실물 보드 장면 (→ 4) |
| 6 | Quality of Github | **4~5** | 영문 README · 빌드/실행 · CI가 핵심 데모 13종(SIL · SDT · 핸드오버 · 모빌리티 · MEC 플랫폼 · 에이전트 · 연합학습 · 모델 전달 · 스웜 · 오케스트레이션 · 구역 방송 · 보안 전송 · 스택/ACL/HA)을 자동 검증. **공개 저장소**(10/11), 최종 영상 · 내레이션 대본 포함. CI 배지, CHANGELOG, CONTRIBUTING · SECURITY · CODE_OF_CONDUCT, 이슈 · PR 템플릿, **심사위원용 반응형 웹**([ljw22112.github.io/Edgeguard](https://ljw22112.github.io/Edgeguard/), 영/한) | 기사 링크 반영 완료(10/11), About 설명 · 토픽 설정 |
| 7 | Promotion of oneM2M | **4** | README 'Why oneM2M' · 기능 표 · 표준 링크, ESTIMED/TR-0077 매핑 문서, 기사가 oneM2M 장점 정리, 심사위원용 웹이 경보 한 건을 oneM2M 요청 단위로 설명 · 기능-표준 조항 표, **HTTP만으로 만드는 10분 oneM2M 튜토리얼**(영/한, CI에서 5/5) | 기사 · 영상 게시 (→ 4~5) |
| 8 | Judge points | **2** | ACME CSE에 버그 2건 공개 보고(10/11): [#199](https://github.com/ankraft/ACME-oneM2M-CSE/issues/199) Content-Type, [#200](https://github.com/ankraft/ACME-oneM2M-CSE/issues/200) MQTT 송신 요청 오류 → **메인테이너가 2026.05.3에서 둘 다 수정(10/12)**, CI를 해당 릴리스로 올리고 #200 수정 덕분에 태그 경보를 MQTT로 받는 기능 추가 | 감사 댓글, sqi=false 시맨틱 탐색 거부 보고, oneM2M 커뮤니티에 소개 글 (→ 2~3) |
| 9 | Interview points | (본선) | 예상 질문 · 답변 16개 ([interview-qa.md](interview-qa.md)): 리소스 트리, oneM2M 장점, 핸드오버, TR-0077 매핑, 보안, 시뮬레이션과 실제의 구분 | 리허설 |
| 10 | Security and Privacy | **5** | **단말별 인증서**(사이트 CA, CN = 발신자) + 브로커 상호 TLS, CRL 폐기 · 키 교체([device_cert.sh](../scripts/device_cert.sh)), TLS(MQTT · HTTPS), 발신자별 ACL, 디바이스 · 앱별 ACP와 chty, 재배치 시 권한 회수. CI에서 인증서 없음 · 다른 CA · 사칭 · 폐기 인증서 · 평문 · 틀린 비밀번호 거부. 작업자 궤적은 현장에만, D2D HMAC | — |
| 11 | Data Interoperability | **5** | SDT 데이터 모델(TS-0023 방식 자체 도메인 + 표준 cod:bat, MEC 데이터 · 호스트 · 배포 의도 · 모델 배포 클래스까지) + SAREF 시맨틱 쿼리, 라벨 탐색으로 자동 등록 | — |
| 12 | CSE Handover | **5** | 위치 · 가용성 · **MEC 네트워크(구역 이벤트)** 트리거, 상태 · 구독 · 보안 컨텍스트 복원, 서비스 중단 1.5~11 ms · 유실 0 측정 ([핸드오버](ko/handover.md), [모빌리티](ko/mobility.md)) | — |
| 13 | oneM2M–MEC App/VM Deployment | **5** | 배포 의도 리소스 하나 → 탐색 · 선택 · 배포 · 등록 · 프로비저닝. **인스턴스마다 실제 컨테이너**(`deploy/edge-app`, CPU · 메모리 제한), 호스트 장애 시 새 컨테이너로 약 2.1~3.0초 만에 재배치, CI에서 `docker ps`로 확인 ([오케스트레이션](ko/orchestration.md)) | ESTIMED VM에서 실행 |
| 14 | Federated Learning (TR-0084) | **5** | 작업 · 참여자 · 라운드 · 모델 버전을 oneM2M 모델로, 동적 선택 · 이탈 · 늦은 참여, 데이터는 사이트에. **전체 수명주기를 오케스트레이터로**: 사이트별 배포 의도 → MEC 호스트에 FL 클라이언트(컨테이너) 배포 → 라벨 탐색 → 학습 → 집계 → 엣지 추론, 호스트 장애 시 다른 사이트로 옮기지 않음(데이터 주권), 의도 하나로 늦은 참여 ([fl_deploy_demo](../tools/fl_deploy_demo.py) 9/9). **모델 전달**: 카나리 · 위험 엔진 활성화 · 섀도 감시 · 롤백 ([모델 전달](ko/swarm-and-model-delivery.md)) | ESTIMED VM에서 실행 (→ 5) |
| 15 | Geolocation Services | **4~5** | MEC 013 구역 이벤트(ENTERING/LEAVING) 구독 → oneM2M → 핸드오버 트리거, 위치 트윈(egs:ueLoc), 구역 그룹 지오펜싱, **영역(원형 지오펜스) · 거리(작업자-지게차 5 m) 구독**을 oneM2M 앱이 IPE로 요청, 실제 위치 대비 검증 ([MEC 플랫폼](ko/mec-platform.md)) | 실제 ETSI Sandbox에서 구독 경로 실행 (→ 5) |
| 16 | MEC Services | **5** | **양방향** MEC–oneM2M(oneM2M 앱이 IPE로 MEC 요청), RNIS 단말별 신호 세기를 SDT(egs:rdLnk)로, 에이전트가 MEC MCP 서버로 소비. **MEC 011 Mp1**(READY, oneM2M 위치를 담은 서비스 등록 · 탐색 · 가용성 알림), **MEC 021 AMS**(이동 트리거 → 컨텍스트 전송 → oneM2M 트윈 핸드오버 → 완료) | Sandbox에서 RNIS 구독 실행 (→ 5) |
| 17 | AI Agents & MCP | **4~5** | (Anthropic API 키를 저장소 Secret `ANTHROPIC_API_KEY`로 넣으면 CI에서 Claude 자유 질문 2개를 도구 호출 · 정답으로 검증)  MCP 서버 4개(IN · 구역 A · 구역 B · ETSI MEC) 오케스트레이션, 다단계 워크플로, 상태를 oneM2M에 저장, 서빙 CSE로 라우팅, 검증 · 오류 처리 ([AI 에이전트](ko/ai-agent.md)) | — |
| | **합계** | **약 70~75 / 85** (인터뷰 제외) | 프로토콜 · 보안 · 배포 5점 | **내레이션 · 회로도 · 커뮤니티 글 · API 키 등록 시 약 71~75** |

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
| 2026-10-11 | 약 63~66 / 85 | ACME 이슈 2건 공개 보고(#199, #200; 8: 0~1 → 1~2), 컨테이너 패키지 2개 공개 |
| 2026-10-12 | 약 66~69 / 85 | 펌웨어 MQTT/TLS(2: 4→5), 단말 인증서 · 상호 TLS · 폐기 · 교체(10: 4→5), 컨테이너 배포(13: 4→5), 실제 MEC 플랫폼용 이벤트 점검 도구, Claude 질문 검증(API 키 필요), 인터뷰 Q&A; ACME 시작 경쟁 조건 수정 |
| 2026-10-14 | 약 67~71 / 85 | MEC 플랫폼 API: MEC 011 Mp1 서비스 등록 · 탐색, MEC 021 AMS를 핸드오버 트리거로(컨텍스트 전송), MEC 013 영역 · 거리 구독(15: 4→4~5, 16: 4→5), CI 데모 10/10 |
| 2026-10-14 | 약 68~72 / 85 | 연합학습 클라이언트를 오케스트레이터가 배포(의도 → 배포 → 탐색 → 학습 → 집계 → 추론, 14: 4~5→5), 참여자 생존 확인, CI에서 스레드 · 컨테이너 모두 실행 |
| 2026-10-14 | 약 69~74 / 85 | 심사위원용 반응형 웹(영/한), CI 배지 · CHANGELOG · 기여 · 보안 · 행동 강령 · 이슈/PR 템플릿(6: 4→4~5, 7: 3→3~4); ACME 최신판(2026.05.3)이 CI를 깨뜨려 검증된 커밋으로 고정 |
| 2026-10-14 | 약 70~74 / 85 | oneM2M 튜토리얼(요청 단위 설명 + 실행 스크립트, CI 5/5, 7: 3~4→4), 웹에 지게차 · 작업자 수 · D2D 모드 설정, 구역 방송 데모의 늦은 전달 집계 |
| 2026-10-15 | 약 70~75 / 85 | ACME가 우리 보고 #199 · #200을 2026.05.3에서 수정(8: 1~2→2); CI 실패 원인은 ACME 2026.05.2+의 numpy 2.5(Python ≥ 3.12 필요) → ACME용 venv를 Python 3.13으로 바꾸고 2026.05.3로 전환; CSE → 태그 경보를 MQTT 알림으로(mqtt_notify_demo 6/6) |
| 2026-10-16 | 약 70~75 / 85 | 고장 주입 장기 실행 시험(CI): CSE 상태 유실 뒤 경보가 영영 복구되지 않던 문제 수정(복구 2.1초), 루프 감독 · 수신 큐 · 테이블 정리, 14/14(수정 전 10/14). 현장 방식 비교(같은 300 에피소드): 넓은 UWB 근접 경보 대비 처리량 +79 %, 경보 −83 %, 좁은 근접 경보 대비 충돌 1/6. 남은 충돌 원인 분석(GO 검사의 작업자 방향 오류 3건) 수정. ACME 버그 3건 보고 초안 |
