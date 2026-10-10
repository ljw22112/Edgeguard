# oneM2M을 통한 연합학습 (TR-0084)

[← README](../../README.ko.md) · [English](../federated-learning.md)

**왜.** 위험도 엔진은 작업자를 등속으로 예측하는데, 이는 사람이 멈추거나 돌려고 속도를 줄일 때 정확히 틀립니다. 학습된 모델이 도움이 되지만 작업자 궤적은 개인정보입니다. 그래서 각 현장(창고의 MEC 호스트)이 자기 데이터로 학습하고, **모델 가중치만 oneM2M으로 오갑니다**. 코디네이터는 위치를 전혀 보지 않습니다.

**모델.** 작은 MLP(16 → 24 → 4)가 등속 추정에 잔차를 더합니다. 최근 0.8 s의 속도로 1 s · 2 s 뒤 변위를 예측합니다. 코드: [`edgeguard/fl.py`](../../edgeguard/fl.py).

## oneM2M 리소스

```
EdgeGuardFL (AE, 코디네이터, IN-CSE)
  task          egs:flTsk   modelName, rounds, currentRound, clientsPerRound, quorum, minSamples,
                            localEpochs, learningRate, roundTimeout, taskStatus, modelVersion
  rounds        CNT         라운드마다 CIN 1개: {round, selected, model_version, deadline_ms, epochs, lr}
  models        CNT         버전마다 CIN 1개: {version, parent, round, participants, weights, metrics}
  acp_fl        코디네이터: 전체 · 클라이언트: 조회 · 탐색 · 알림 · 구독 생성만
fl_<site> (AE, 클라이언트마다 1개, 클라이언트가 생성)
  participant   egs:flPrt   site, sampleCount, available, computeScore, lastRound, modelVersion, participantStatus
  updates       CNT         학습한 라운드마다 CIN 1개: {round, n, weights, loss, base_version}
  acp_fl        클라이언트: 전체 · 코디네이터: 조회 · 탐색 · 알림 · 구독 생성만
subscriptions   각 클라이언트 → rounds (내가 선택됐나?) · 코디네이터 → 모든 updates 컨테이너
```

## 라운드 진행

1. **탐색**: 라벨(`egs:fl/participant`)로 참여자를 찾고 상태를 읽습니다. 지난 라운드 이후 등록한 클라이언트는 여기서 합류합니다.
2. **선택**: 가용하고 `minSamples` 이상을 가진 클라이언트를 최대 `clientsPerRound`개 고릅니다. 가장 오래 기다린 쪽, 다음으로 계산 점수가 높은 쪽을 우선합니다.
3. **공지**: `rounds`에 CIN을 만듭니다. 선택된 클라이언트는 `models`의 최신 모델에서 학습하고 가중치를 자기 `updates`에 올립니다.
4. **집계**: 선택된 클라이언트가 모두 답하거나 제한 시간이 지나면 FedAvg(샘플 수 가중)로 집계합니다. 현재 버전 기반 업데이트가 `quorum`개 이상 필요하고, 모자라면 모델을 유지한 채 라운드를 반복합니다.
5. **발행**: 새 버전을 부모 · 참여자(계보)와 함께 발행하고 `task.modelVersion`을 갱신합니다.

## 실행

```bash
scripts/acme.sh start in
python tools/fl_demo.py            # 8개 확인, CI에서도 실행; results/fl.json
```

**시나리오:**
- 서울 · 부산 · 인천으로 시작합니다.
- 라운드 3 학습 도중 인천의 MEC 호스트가 고장 나고, 라운드는 나머지 둘로 집계됩니다(quorum 2).
- 대전이 라운드 4 전에 등록하고 바로 선택됩니다.
- 인천이 라운드 6에 복귀합니다.

| 2 s 예측 오차, 검증 데이터, 4개 현장 평균 | m |
|---|---|
| 등속 | 0.604 |
| 현장별 단독 학습 (모든 현장에서 평가) | 0.521 |
| **연합 전역 모델** | **0.486** |

**확인 항목:**
- task 리소스가 실행을 추적
- 오프라인 클라이언트는 오프라인 동안 선택되지 않음
- 이탈 허용
- 늦게 합류한 참여자 선택
- 업데이트에는 가중치만 담김 (위치 없음; 크기 = 4바이트 × 파라미터 수)
- 모델 계보 완전
- 전역 모델이 모든 현장에서 등속보다 나음
- 전역 모델이 단독 학습 모델보다 일반화가 잘 됨

## 한계

- 보행 데이터는 측정한 태그가 아니라, 현장별 배치 · 속도 · 멈춤/회전 습관을 둔 현장 시뮬레이터에서 나옵니다.
- 학습된 모델은 아직 온라인 위험도 엔진에서 쓰지 않습니다. MEC 앱으로 모델을 배포하는 것이 다음 단계입니다.
- 실험은 ACME에서 했습니다. 설계는 ESTIMED 개념 검증의 역할을 따르며 ESTIMED VM에서 실행하도록 만들었습니다.
