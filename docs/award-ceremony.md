# Award ceremony: video and script

[← README](../README.md)

Video: `results/edgeguard_award.mp4` (2 min 56 s, silent, cards and demo, built by [`tools/make_award_video.py`](../tools/make_award_video.py)). The team speaks over it; the acceptance speech follows when it ends. About 3 min 50 s in total.

## While the video plays

| Video | On screen | Speaker | Say (about 130 words per minute) |
|---|---|---|---|
| 0:00 – 0:30 | Title, "Why this topic" | Jeongwon | Hello everyone, we are Team EdgeGuard from Sejong University. We chose this topic because forklifts and people share the same aisles: in Korea, over two and a half thousand people were hurt or killed in two years. And today's alarms make sites choose: set them wide, and trucks lose half their work; narrow them, and collisions get through. |
| 0:30 – 1:13 | WAIT / STEP ASIDE / GO, "How we built it", architecture | Jeongwon | So we asked a different question: not how close, but will they meet? We started with a simple vibration alert, and it let a hundred collisions through. Then we told each person what to do: wait, step aside, or go. Then we let the truck keep its speed and brake for a stop point by itself. Every time our simulator found a collision, we traced it, fixed the cause in both the Python code and the firmware, and tested again on new episodes. All of it runs on oneM2M CSEs and ETSI MEC, one MEC host per zone. |
| 1:13 – 2:00 | Live demo | Kihwan | Here it is running. The worker crossing gets WAIT, and GO once the forklift has passed. The worker standing in the lane is told to step aside. With two forklifts, GO comes only after both have passed. Every position and every alert is a oneM2M resource. |
| 2:00 – 2:22 | Firmware in the loop | Kihwan | This is our ESP32 firmware, unchanged, talking to a real oneM2M CSE, with a phone as the worker's tag. |
| 2:22 – 2:36 | Mobility map | Kihwan | And when the forklift moves to another zone, an ETSI MEC event moves its oneM2M twin to that zone's CSE, in a few milliseconds and without losing data. |
| 2:36 – 2:56 | Results, Thank you | Kihwan | In simulation, EdgeGuard was as safe as the widest alarm, at twice the throughput. And on bad days, with network loss, server restarts and people who don't look, no moving truck touched anyone. |

If the video runs ahead, skip a sentence; never talk over the end card. If it stalls, keep talking: every sentence also works without the picture.

## Acceptance speech (after the video, about 50 s)

**Jeongwon:** Thank you so much to oneM2M, ETSI and the ESTIMED team for organizing this hackathon, and to the judges for their time and their questions. We learned a lot from them, and also from the people who build the open tools we used: the ACME and tinyIoT CSEs, and the ETSI MEC Sandbox. When we reported two bugs in ACME, they were fixed within weeks, which showed us how open this community is.

**Kihwan:** For us, this project was about one idea: safety and productivity don't have to be a trade-off. Our next steps are a demo on real boards and a pilot at a real site. And since oneM2M is working on MCP servers, we would be glad to share what we learned there. Thank you, and congratulations to all the other teams.

## Korean summary (for practice)

| 구간 | 요지 |
|---|---|
| 0:00 – 0:30 (jw) | 팀 소개. 주제 선정 이유: 지게차와 사람이 같은 통로를 씀, 2년간 사상자 2,559명, 기존 경보는 안전과 생산성 중 하나를 골라야 함 |
| 0:30 – 1:13 (jw) | 개발 과정: "얼마나 가까운가"가 아니라 "만나는가". 진동 경보(충돌 100건) → WAIT·STEP ASIDE·GO → 트럭이 스스로 정지 지점에 맞춰 제동. 충돌마다 원인 추적 → 파이썬·펌웨어 수정 → 새 에피소드로 재시험. oneM2M CSE와 ETSI MEC 위에서 구역마다 MEC 호스트 |
| 1:13 – 2:36 (기환) | 데모 설명: WAIT→GO, STEP ASIDE, 지게차 2대, 모든 위치·경보가 oneM2M 리소스 / ESP32 펌웨어가 실제 CSE와 통신, 휴대폰이 태그 / MEC 이벤트로 구역 간 트윈 이동, 수 ms, 데이터 손실 없음 |
| 2:36 – 2:56 (기환) | 결과: 넓은 경보만큼 안전하면서 처리량 2배, 예외 상황에서도 움직이는 지게차가 사람에 닿은 경우 없음 |
| 소감 (jw) | oneM2M · ETSI · ESTIMED 팀과 심사위원께 감사, ACME · tinyIoT · MEC Sandbox 등 오픈 도구에서 많이 배움, ACME 버그 보고가 몇 주 만에 수정되어 열린 커뮤니티를 느낌 |
| 소감 (기환) | 안전과 생산성은 둘 중 하나가 아니다. 다음은 실제 보드 시연과 현장 시범, oneM2M MCP 표준화에 경험 공유하고 싶음. 감사, 다른 팀들 축하 |
