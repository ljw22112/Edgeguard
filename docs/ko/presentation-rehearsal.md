# 본선 발표 연습 자료

[← README](../../README.ko.md) · 영문 대본 원본: [final-presentation.md](../final-presentation.md) · 예상 질문 전체: [interview-qa.md](../interview-qa.md)

발표 자료(Slides, 15장)의 발표자 노트와 같은 대본입니다. 슬라이드마다 **영어 대본 → 한국어 뜻 → 외울 숫자 → 다음 장으로 넘기는 말**을 정리했습니다. 발표 시간이 정해지면 아래 "시간별 버전"에서 고르면 됩니다.

## 한눈에

| | |
|---|---|
| 전체 길이 | 약 1,650단어, 분당 140단어로 약 12분 |
| 역할 나누기(제안) | **jw: 1~8장**(문제 · 방법), **김기환: 9~15장**(근거 · 사업성 · 마무리). 8장 끝에서 넘김 |
| 넘길 때 하는 말 | jw: "Now my teammate will show you the evidence." → 김기환: "Thank you. Now the evidence." |
| 꼭 지킬 것 | 수치는 모두 **시뮬레이션**이라고 말하기(9 · 10 · 14장). 숫자는 화면에 있으니 외우되 읽지 않기 |

## 외울 숫자 10개

| 숫자 | 뜻 | 말하는 법 |
|---|---|---|
| 2,559 | 한국 지게차 사고 사상자(2021~2022) | two thousand five hundred fifty-nine |
| $116k | 부상 1건 총비용(간접비 포함) | about one hundred sixteen thousand dollars |
| 48 % / 49 | 넓은 근접 경보 처리량 / 좁힌 경보 충돌 | forty-eight percent / forty-nine collisions |
| 0 · 97.3 % · 2.0× | EdgeGuard 충돌 · 처리량 · 근접 경보 대비 | zero, ninety-seven point three, twice |
| −81 % | 경보 수 감소 | eighty-one percent fewer alarms |
| 30 → 0 | 예외 상황 충돌(이전 정책 → v3.1) | thirty to zero |
| 34,644 | 예외 상황 충돌 상황 수 | thirty-four thousand six hundred forty-four |
| 0.11 | 95 % 상한, 1,000건당 | upper bound zero point one one per thousand |
| 25 ms | 엣지 경보 지연 중앙값(클라우드 85 ms) | twenty-five milliseconds |
| 1.38 → 0.07 s | 조우당 지게차 손실(근접 경보 → EdgeGuard) | one point four seconds to under a tenth |

## 발음

| 용어 | 읽는 법 |
|---|---|
| oneM2M | "one-em-two-em" |
| ETSI | "ET-see" |
| MEC | "mek" (또는 "M-E-C", 한 가지로 통일) |
| CSE · AE · ACP · SDT | 알파벳 그대로 "C-S-E", "A-E", "A-C-P", "S-D-T" |
| UWB | "U-W-B" |
| SAREF | "SAH-ref" |
| Mobius · ACME | "MOH-bee-us" · "AK-mee" |
| TR-0077 · TR-0084 | "T-R zero zero seven seven" |
| ESP32 | "E-S-P thirty-two" |

---

## 슬라이드별 대본

### 1. EdgeGuard (표지) · 약 30초 · jw

> Good morning. We are Team EdgeGuard from Sejong University. EdgeGuard predicts collisions between warehouse workers and forklifts one to three seconds ahead, on the network edge, and tells each person exactly what to do: wait, step aside, or go. It is built on oneM2M and ETSI MEC. In the next ten minutes: why today's systems force sites to choose between safety and productivity, how EdgeGuard works, and the evidence that it gives both.

**뜻:** 세종대 EdgeGuard 팀입니다. 작업자와 지게차의 충돌을 1~3초 앞서 네트워크 엣지에서 예측하고, 각자에게 기다려 · 비켜서 · 가라고 알려 줍니다. oneM2M과 ETSI MEC 위에 만들었습니다. 지금 시스템이 왜 안전과 생산성 중 하나를 고르게 만드는지, EdgeGuard가 어떻게 동작하는지, 둘 다 된다는 근거를 보여 드리겠습니다.

**넘기는 말:** "Let's start with the problem."

### 2. 같은 통로를 쓰는 사람과 지게차 · 약 35초 · jw

> Forklifts and people share the same aisles. In Korea alone, two thousand five hundred fifty-nine people were hurt or killed in forklift accidents in two years. One injury costs a company about one hundred sixteen thousand dollars once indirect costs are counted, and in Korea a fatal accident can also bring criminal liability for executives. The hard part is time: at a blind corner, a walker may have two seconds between seeing a truck and being hit.

**뜻:** 한국에서만 2년간 2,559명이 지게차 사고로 다치거나 숨졌습니다. 부상 1건은 간접비까지 약 11.6만 달러, 사망 사고는 경영자 형사 책임까지 따릅니다. 문제는 시간입니다. 사각 모퉁이에서는 트럭을 보고 부딪히기까지 2초밖에 없을 수 있습니다.

**외울 것:** 2,559 · $116k · 2초 · **넘기는 말:** "So what do sites use today?"

### 3. 근접 경보의 딜레마 · 약 45초 · jw

> What do sites use today? Speed limits, and UWB proximity alarms: a tag on the worker, an anchor on the truck. We modelled one the way commercial systems work: a warning zone where the truck slows to walking speed, a danger zone where it stops. Set wide, at six and three metres, it prevented every collision in our test, but trucks ran at forty-eight percent of their normal throughput. So sites narrow the zones. At four and two metres the nuisance drops, but forty-nine collisions got through. The root cause is that a distance alarm has no notion of direction.

**뜻:** 현장은 속도 제한과 UWB 근접 경보를 씁니다. 상용 제품처럼 경고 구역에서는 보행 속도로 감속, 위험 구역에서는 정지하도록 모델링했습니다. 6 m / 3 m로 넓히면 충돌은 다 막지만 처리량이 48 %, 그래서 4 m / 2 m로 좁히면 49건이 뚫립니다. 거리 경보는 방향을 모르기 때문입니다.

**강조:** "no notion of direction"에서 잠깐 멈추기 · **넘기는 말:** "EdgeGuard asks a different question."

### 4. 충돌 경로를 예측하고 할 일을 알려 준다 · 약 50초 · jw

> EdgeGuard asks a different question: not how close, but will they meet. The test comes from missile guidance: if the bearing stays constant while the range closes, two objects are on a collision course. A truck that will pass by never raises an alert. When a meeting is coming, the worker's tag says WAIT, and GO once the truck has passed, or STEP ASIDE if the worker is standing in the lane. The truck keeps its speed as long as it can still stop short of the person; when it cannot, it gets a stop point and brakes for it by itself. The decision runs on the ETSI MEC edge in about twenty-five milliseconds, and everything is a oneM2M resource.

**뜻:** "얼마나 가까운가"가 아니라 "만나게 되는가"를 묻습니다. 미사일 유도의 판정(방위각은 그대로인데 거리가 줄면 충돌 경로)을 씁니다. 지나갈 트럭에는 경보가 없습니다. 만나게 되면 태그가 WAIT, 지나가면 GO, 통로에 서 있으면 STEP ASIDE. 트럭은 사람 앞에서 멈출 수 있는 동안 속도를 유지하고, 안 되면 정지 지점을 받아 스스로 제동합니다. 판단은 MEC 엣지에서 약 25 ms, 모든 것이 oneM2M 리소스입니다.

**넘기는 말:** "Here is how it is built."

### 5. 구역마다 MEC 호스트 · 약 45초 · jw

> Here is the architecture. Each warehouse zone has a MEC host with a oneM2M MN-CSE. Worker tags and forklift modules register their own application entities on that CSE. The EdgeGuard MEC app runs next to it as a container: it subscribes to positions, decides, and writes alerts back as oneM2M resources, which the CSE pushes to the tags and forklifts. A MEC interworking proxy brings ETSI MEC location and radio information into the same CSE. In the cloud, an IN-CSE holds home records for devices moving between zones, runs federated learning across sites, and hosts the AI safety agent. In ESTIMED terms this is deployment option C.

**뜻:** 구역마다 MEC 호스트와 MN-CSE가 있고, 태그와 지게차 모듈이 각자 AE를 등록합니다. MEC 앱은 옆에서 컨테이너로 돌며 위치를 구독하고 판단해 경보를 oneM2M 리소스로 씁니다. MEC-IPE가 MEC 위치 · 무선 정보를 같은 CSE로 가져옵니다. 클라우드 IN-CSE는 구역 이동 기록, 연합학습, AI 에이전트를 맡습니다. ESTIMED 배치 옵션 C입니다.

**화면:** 그림에서 구역 → MEC 앱 → IN-CSE 순서로 손으로 짚기 · **넘기는 말:** "Why oneM2M?"

### 6. CSE가 서버 일을 대신한다 · 약 60초 · jw

> Why oneM2M? Because the CSE does the work our own server would otherwise have to do. Subscriptions replaced a broker and polling code. Device twins are SDT flexContainers with labels and SAREF semantics, so a new tag is found by one discovery request and onboarded in about nine seconds, without a device list. Access control is built in: one ACP per device, and with a child-type restriction the MEC app can create subscriptions in a twin but never write data into it. A group fan-out point sends one DANGER alert to every tag in a zone in a single request, and polling channels reach tags behind NAT. Announcement and CSE handover let a forklift's presence move between zones. Devices use the MQTT binding over mutual TLS. The same code runs on Mobius and ACME, and we reported two bugs to ACME along the way.

**뜻:** 구독이 브로커와 폴링 코드를 대신합니다. 단말 트윈은 SDT flexContainer + 라벨 + SAREF라 탐색 한 번으로 약 9초 만에 등록됩니다. ACP는 단말마다 하나, chty 제한으로 MEC 앱은 구독만 만들고 데이터는 못 씁니다. 그룹 팬아웃으로 DANGER 한 번에 구역 전체 태그, 폴링 채널로 NAT 뒤 태그까지. announcement와 핸드오버로 구역 이동, MQTT 상호 TLS, Mobius · ACME 같은 코드, ACME에 버그 2건 보고.

**8분 버전에서 줄이는 법:** 굵게 표시한 세 가지만 말하기: subscriptions, ACP with child-type, group fan-out · **넘기는 말:** "And ETSI MEC."

### 7. MEC 서비스를 oneM2M으로, 양방향 · 약 50초 · jw

> ETSI MEC services reach our application through oneM2M. A MEC interworking proxy subscribes to MEC 013 zone events and MEC 012 per-device signal strength and writes them into the CSE as SDT twins; oneM2M applications can also post MEC requests the other way. A zone event triggers the CSE handover, with one and a half to eight milliseconds of interruption and no samples lost. Applications are deployed by intent: one oneM2M resource drives discovery, host selection, deployment and Mp1 service registration, and when a host crashes the app runs again elsewhere in two to three seconds. On the edge the median alert latency is twenty-five milliseconds, against eighty-five for a cloud-only path. We ran this live on the public ETSI MEC Sandbox.

**뜻:** MEC-IPE가 MEC 013 구역 이벤트와 MEC 012 신호 세기를 SDT 트윈으로 쓰고, 반대로 oneM2M 앱이 MEC 요청도 보냅니다. 구역 이벤트가 핸드오버를 시작(중단 1.5~8 ms, 유실 0). 배치 의도 리소스 하나로 탐색 · 선택 · 배포 · Mp1 등록, 호스트 장애 시 2~3초 만에 재배치. 엣지 지연 25 ms(클라우드 85 ms), 공개 ETSI MEC Sandbox에서 실행.

**넘기는 말:** "A safety system is judged by its bad days."

### 8. 서버가 없어도 안전한 4중 보호 · 약 65초 · jw

> A safety system is judged by its bad days, so protection is layered. The MEC app does the prediction and the guidance, and a standby takes over in under a second. Stop points live on the truck: the module brakes for its point from its own position every cycle, so a lost or late message does not delay braking. Devices broadcast their state to each other directly, signed, and when the MEC app goes quiet, for example after a restart, the tag checks for itself whether it is safe to walk on. And the last line is an always-on emergency brake on the forklift module: a person on a collision course within one and a half seconds stops the truck, and since version 3.1 the truck stays stopped while that person is in front of it. All of this is the same code in our Python reference and the ESP32 firmware, and CI checks that they agree.

**뜻:** 보호는 네 겹입니다. ① MEC 앱(대기 서버가 1초 안에 인계) ② 트럭이 자기 위치로 정지 지점에 맞춰 제동(메시지 지연과 무관) ③ 단말 간 직접 상태 방송, MEC가 조용하면 태그가 GO를 스스로 확인 ④ 상시 긴급제동(1.5초 안 충돌 경로면 정지, v3.1부터 사람이 앞에 있는 동안 유지). 파이썬과 ESP32 펌웨어가 같은 코드이고 CI가 일치를 확인.

**넘기는 말(역할 교대):** "Now my teammate will show you the evidence."

### 9. 넓은 경보만큼 안전, 처리량은 두 배 · 약 40초 · 김기환

> Now the evidence. Every system ran on the same one thousand simulated episodes: eight workers, four forklifts, three thousand six hundred seventeen conflicts, and nobody looks out, so this is what each system alone prevents. These episodes were never used to train, select or tune our policy. EdgeGuard had zero collisions, like the wide proximity alarm, but trucks kept ninety-seven point three percent of their throughput, twice the alarm's forty-eight. It raised eighty-one percent fewer alarms and halved the time workers spent waiting. Against the narrowed alarm, it is zero collisions instead of forty-nine and thirty-seven points more throughput.

**뜻:** 모든 방식을 같은 시뮬레이션 에피소드 1,000개(작업자 8, 지게차 4, 충돌 상황 3,617건, 아무도 주의 안 함)로 돌렸고, 정책 학습 · 선택 · 조정에 쓰지 않은 에피소드입니다. EdgeGuard는 넓은 경보처럼 충돌 0인데 처리량 97.3 %로 두 배, 경보 81 % 감소, 대기 시간 절반. 좁힌 경보 대비 충돌 49 → 0, 처리량 +37 %p.

**강조:** "never used to train, select or tune" · **넘기는 말:** "But a safety system has to hold up on bad days."

### 10. 예외 상황 30건 → 0건 · 약 45초 · 김기환

> A safety system has to hold up on bad days. We ran eight thousand more fresh episodes under eight conditions: a bad network with up to six hundred milliseconds of delay and forty percent loss, the MEC app restarting and losing its state, workers who ignore fifteen or thirty percent of alerts, noisy positioning, a dense floor and attentive drivers. Our previous policy had thirty collisions in thirty-four thousand six hundred forty-four conflicts. The current version, 3.1, had none; the upper bound of the ninety-five percent interval is about one in nine thousand conflicts. And trucks were faster in every scenario, by five to ten points.

**뜻:** 8가지 조건(지연 600 ms · 손실 40 %의 불량 통신, 상태를 잃는 MEC 재시작, 경보 15 · 30 % 무시, 측위 오차, 밀집, 주의 깊은 운전자)에서 새 에피소드 8,000개. 이전 정책 30건, v3.1은 0건, 95 % 상한은 약 9,000건에 1건. 모든 조건에서 트럭이 5~10 %p 더 빨랐습니다.

**넘기는 말:** "How did we get to zero?"

### 11. 충돌마다 추적 → 원인 수정 → 새 시드로 재시험 · 약 55초 · 김기환

> How did we get to zero? Not by tuning until the numbers looked good. Every collision the simulator found was traced to its cause, fixed in both the Python reference and the firmware, and checked again on seeds the fix had never seen. Four examples: stop points that crept away with position noise; a sidestep that led a worker into a second truck; a WAIT lost when the MEC app restarted, which led to the tag checking GO itself; and in version 3.1, an emergency stop that released while the person still stood in front of the truck. We train, select and test on separate seeds, and we reject candidates that are faster but less safe. The safety case lists six hazards and eight claims, each linked to the tests that are its evidence.

**뜻:** 숫자가 좋아질 때까지 조정한 게 아닙니다. 충돌마다 원인을 추적해 파이썬과 펌웨어 둘 다 고치고, 본 적 없는 시드로 다시 확인했습니다. 예: 위치 오차로 밀리던 정지 지점, 두 번째 트럭 쪽으로 보낸 STEP ASIDE, MEC 재시작으로 잃은 WAIT(→ 태그 자체 GO 확인), v3.1의 풀려 버린 긴급 정지. 학습 · 선택 · 시험 시드를 분리하고, 빠르지만 덜 안전한 후보는 버립니다. 안전성 논증: 위험원 6, 주장 8, 각 근거 시험 연결.

**넘기는 말:** "Beyond a single zone."

### 12. 사이트 간 학습 · 협조하는 트럭 · 보고하는 에이전트 · 약 50초 · 김기환

> Beyond a single zone. Worker trajectories are personal data, so each site trains a small motion model on its own data, and only the weights travel through oneM2M, following TR-0084. The two-second prediction error dropped from sixty to forty-nine centimetres, and new models go through canary, activation and rollback. Forklifts form a swarm: they share their plans through a oneM2M group and each computes the same conflict-free schedule, cutting total delay from twenty-three and a half seconds to fourteen and a half. And an AI safety agent writes shift reports by calling MCP servers for the cloud CSE, both zone CSEs and ETSI MEC. Every one of these demos runs in CI on every commit.

**뜻:** 궤적은 개인정보라 사이트마다 학습하고 가중치만 oneM2M으로(TR-0084). 2초 예측 오차 60 → 49 cm, 카나리 · 활성화 · 롤백. 지게차 스웜은 그룹으로 계획을 공유해 같은 무충돌 일정 계산(총 지연 23.5 → 14.5초). AI 에이전트가 MCP 서버(IN-CSE, 구역 CSE 2, ETSI MEC)로 교대 보고서 작성. 모두 CI에서 매 커밋 실행.

**넘기는 말:** "Is it worth it?"

### 13. 저가 단말, 지게차 시간으로 회수 · 약 50초 · 김기환

> Is it worth it? A ten-thousand-square-metre warehouse with fifty workers and ten forklifts costs about fifteen thousand dollars up front, with low-cost ESP32 and UWB devices and two edge servers. Against a proximity alarm, a forklift loses one point four seconds per encounter with a person; with EdgeGuard, under a tenth of a second. At ten to thirty encounters an hour that pays the system back in one to three and a half years on time alone, and a single prevented injury pays for it eight times. Revenue comes from the hardware kit, a subscription, and bundling with operators' private 5G and MEC offers. And because alerts are oneM2M resources, a site's warehouse system can use them simply by subscribing.

**뜻:** 1만 m², 작업자 50, 지게차 10 현장에 초기 비용 약 1.5만 달러. 근접 경보는 조우당 1.4초, EdgeGuard는 0.1초 미만 손실. 시간당 10~30회 조우면 시간만으로 1~3.5년에 회수, 부상 1건 예방이면 8배. 수익: 하드웨어 키트, 구독, 통신사 사설 5G · MEC 상품. 경보가 oneM2M 리소스라 WMS가 구독만으로 사용.

**넘기는 말:** "We want to be clear about scope."

### 14. 실제인 것과 시뮬레이션인 것 · 약 50초 · 김기환

> We want to be clear about scope. What is real and checked on every commit: the oneM2M resources on real Mobius and ACME CSEs; the ESP32 firmware, compiled unmodified for a PC and run against a real CSE over HTTP, MQTT and mutual TLS; handover, orchestration, federated learning and the agent; and live runs on the public ETSI MEC Sandbox. What is simulated: the workers and drivers, and therefore the collision and throughput figures; and the proximity alarm uses typical settings, not one product's. Running people, people hidden from UWB and unplanned reversing are not covered yet. The next step is a board demo and a pilot at a site, measured with near-miss data.

**뜻:** 실제: 진짜 Mobius · ACME 위의 oneM2M 리소스, PC로 그대로 컴파일한 ESP32 펌웨어를 HTTP · MQTT · 상호 TLS로 실제 CSE에 연결, 핸드오버 · 오케스트레이션 · 연합학습 · 에이전트, 공개 ETSI MEC Sandbox 실행. 시뮬레이션: 작업자 · 운전자 행동, 그래서 충돌 · 처리량 수치. 근접 경보는 대표 설정. 뛰는 사람, UWB에 가려진 사람, 계획 없는 후진은 아직. 다음: 보드 시연과 현장 시범.

**넘기는 말:** "To sum up."

### 15. 마무리 · 약 25초 · 김기환

> To sum up: today sites choose between a safe alarm and a productive one. EdgeGuard gives both: zero collisions at twice the throughput of a proximity alarm, and zero in thirty-four thousand conflicts on bad days, built on standard oneM2M and ETSI MEC. The code, the judge site and the video are linked here. Thank you, we are happy to take your questions.

**뜻:** 지금은 안전한 경보와 생산적인 경보 중 하나를 고릅니다. EdgeGuard는 둘 다: 근접 경보 대비 처리량 두 배에서 충돌 0, 예외 상황 3만 4천 건에서도 0. 표준 oneM2M과 ETSI MEC 위에 만들었습니다. 감사합니다, 질문 받겠습니다.

---

## 시간별 버전

| 발표 시간 | 쓰는 슬라이드 | 바꾸는 것 |
|---|---|---|
| **12분** | 1~15 전부 | 그대로 |
| **8~9분** | 7 · 12 · 14 건너뜀(발표 모드에서 숨기기) | 6장은 세 가지만(위 표시). 5장 끝에 한 문장 추가: "MEC zone events also trigger the CSE handover, in a few milliseconds." 14장 내용은 질의응답에서 |
| **5분** | 1 · 3 · 4 · 5 · 8 · 9 · 10 · 11 · 13 · 15 | 아래 5분 대본(약 500단어, 쉼 포함 약 4분 반) |

### 5분 대본

> **[1]** Good morning, we are Team EdgeGuard from Sejong University. EdgeGuard predicts collisions between warehouse workers and forklifts one to three seconds ahead, on the ETSI MEC edge, and tells each person exactly what to do: wait, step aside, or go. It is built on oneM2M.
>
> **[3]** Forklift accidents hurt thousands of people every year, and one injury costs a company over a hundred thousand dollars. Sites today use UWB proximity alarms. We modelled one the way commercial systems work. Set wide, at six and three metres, it prevented every collision in our test, but trucks ran at forty-eight percent of their normal throughput. Narrowed to four and two metres to stop the nuisance, forty-nine collisions got through. A distance alarm has no notion of direction.
>
> **[4]** EdgeGuard asks a different question: not how close, but will they meet? If the bearing stays constant while the range closes, two objects are on a collision course, so a truck that will pass by never raises an alert. When a meeting is coming, the worker's tag says WAIT, then GO once the truck has passed, or STEP ASIDE if the worker stands in the lane. The truck keeps its speed while it can still stop short of the person; otherwise it gets a stop point and brakes for it by itself.
>
> **[5]** Each warehouse zone has a MEC host with a oneM2M CSE. Tags and forklift modules register their own AEs. Our MEC app subscribes to their positions, decides in about twenty-five milliseconds, and writes alerts back as oneM2M resources. ETSI MEC location and radio data reach it through oneM2M too, and MEC zone events trigger the CSE handover when a forklift moves between zones, in a few milliseconds.
>
> **[8]** If the network or the app fails, people stay protected: the truck executes its stop point itself, devices exchange their state directly, the tag checks GO on its own, and an always-on emergency brake stops the truck for a person right in its path.
>
> **[9]** Now the evidence, in simulation, on one thousand episodes we never used to train or tune our policy. EdgeGuard had zero collisions, like the wide alarm, at ninety-seven percent throughput, twice the alarm's, with eighty-one percent fewer alarms.
>
> **[10]** On eight thousand more episodes with a bad network, server restarts, workers who ignore alerts and noisy positioning, our previous policy had thirty collisions. The current one had none in thirty-four thousand conflicts, and trucks were faster in every condition.
>
> **[11]** We got there by tracing every collision to its cause, fixing it in both the Python reference and the ESP32 firmware, and retesting on seeds the fix had never seen. A safety case ties each claim to its tests.
>
> **[13]** A ten-thousand-square-metre site costs about fifteen thousand dollars, paid back in one to three and a half years on forklift time alone.
>
> **[15]** EdgeGuard: safe and productive, not one or the other, on standard oneM2M and ETSI MEC. Thank you, we are happy to take your questions.

---

## 질의응답: 30초 답변

길게 말하지 말고 **답 → 숫자 하나 → 근거 문서**. 모르면 "We haven't measured that yet; our next step is ..."로 정직하게. 전체 23개는 [interview-qa.md](../interview-qa.md).

| 질문 | 영어 답 (말하는 그대로) | 뜻 |
|---|---|---|
| Zero collisions sounds too good. | "It's zero in simulation, on episodes we never used to train or tune. We report intervals: the upper bound is about one in nine thousand conflicts, and our previous policy's interval sits well above it." | 학습에 안 쓴 에피소드에서의 시뮬레이션 0, 95 % 상한 약 9,000건에 1건 |
| Why oneM2M, not plain MQTT? | "Because the CSE gives us subscriptions, access control per device, discovery and group fan-out out of the box, and other apps like a WMS can use our alerts just by subscribing." | 구독 · 단말별 ACP · 탐색 · 그룹 팬아웃 기본 제공, 다른 앱이 구독만으로 사용 |
| What does MEC add? | "Latency and locality: twenty-five milliseconds at the edge against eighty-five in the cloud, trajectories stay on site, and MEC zone events drive the handover." | 지연(25 vs 85 ms), 데이터가 현장에, 구역 이벤트로 핸드오버 |
| What if the network fails? | "Four layers. Stop points are executed on the truck, devices exchange state directly, the tag checks GO itself, and the emergency brake is always on. Under bad network and restart scenarios: zero collisions." | 4중 보호, 불량 통신 · 재시작 시나리오 충돌 0 |
| Is the alarm comparison fair? | "Same floor, same episodes, same noise for every system. The alarm follows how commercial UWB systems behave, with two zone settings sites use. With an attentive driver the result is the same." | 같은 조건, 상용 동작 모사, 주의 깊은 운전자에서도 동일 |
| Did you test with real hardware? | "The firmware runs unmodified against a real CSE in CI over HTTP, MQTT and mutual TLS. The physical board demo and a site pilot are our next step." | 펌웨어는 CI에서 실제 CSE와, 보드 시연 · 현장 시범은 다음 단계 |
| What changed in v3.1? | "Our last two collisions came after an emergency stop released while the person still stood in front. The brake now holds while he is in the truck's path." | 긴급 정지 후 사람이 앞에 있는 동안 유지 |
| Will workers obey WAIT? | "We modelled workers who ignore fifteen and thirty percent of alerts: still zero collisions. WAIT lasts only until the truck has passed, and alarms are eighty-one percent fewer, so less fatigue." | 15 · 30 % 무시해도 0, 경보 81 % 감소 |
| How much, and payback? | "About fifteen thousand dollars for a ten-thousand-square-metre site. One to three and a half years on forklift time alone; one prevented injury pays for it eight times." | 약 1.5만 달러, 1~3.5년, 부상 1건이면 8배 |
| Privacy? | "Trajectories stay in the zone's edge CSE. Only alerts and near-miss events leave the site, and federated learning moves weights, not data." | 궤적은 엣지에, 경보 · 아차사고만 외부로, 연합학습은 가중치만 |

## 리허설 순서

1. 혼자 소리 내어 읽기: 슬라이드마다 시간 재기(위 목표 시간 ± 10초)
2. 숫자 10개를 화면 없이 말하기
3. 둘이서 통으로: 8장 → 9장 교대 연습, 전체 시간 확인
4. 질의응답: 한 사람이 위 표 질문을 무작위로, 30초 안에 답하기
5. 발표 당일 백업: 발표 자료 PDF와 `results/edgeguard_final.mp4`를 노트북에 받아 두기(인터넷이 끊겨도 진행)
