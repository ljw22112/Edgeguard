# 공개 · 게시 체크리스트 (팀 작업)

[← README](../README.ko.md)

계정 로그인이 필요해 사람이 마지막 클릭을 해야 하는 일들입니다. 순서대로 하면 루브릭 4 · 5 · 6 · 7 · 8번 점수가 오릅니다.

## 1. 저장소 공개 · 루브릭 6, 7: 완료 (10/11)

전체 커밋 이력에서 비밀번호 · 토큰 · 키 파일 · 공인 IP · ssh 접속 정보를 검사했고 나온 것은 없습니다. 데모용 인증서와 비밀번호는 실행할 때 `.certs/`에 생성되며, 이 폴더는 커밋되지 않습니다.

1. ~~Danger Zone → Make public~~ 완료
2. ~~(선택) Packages → `edgeguard-mobius`, `edgeguard-mec` → Package settings → **Change visibility → Public**~~ 완료 (10/11): `docker compose`가 로그인 없이 이미지를 받을 수 있게 됩니다.
3. ~~저장소 첫 화면 오른쪽 About 톱니바퀴~~ 완료 (10/11): Description에 `Worker–forklift collision prediction on oneM2M + ETSI MEC (2026 oneM2M Hackathon)`, Topics에 `onem2m`, `etsi-mec`, `iot`, `edge-computing`, `safety`, `acme-cse`, `mobius` 입력

## 2. 영상 업로드 · 루브릭 5: 완료 (10/11, https://youtu.be/P2JI5ZG6PIg)

- 파일: `results/edgeguard_final.mp4`(2분 34초, 자막 `results/edgeguard_final.srt`)
- 내레이션 녹음(선택): [video-script.md](video-script.md) 대본을 읽어 녹음한 뒤 문서의 ffmpeg 명령으로 합칩니다.
- YouTube 업로드: 공개 또는 일부 공개, 자막 파일(.srt)도 함께 올립니다.
- 제목 예시: `EdgeGuard – Forklift collision prediction with oneM2M and ETSI MEC (2026 oneM2M Hackathon)`

## 3. hackster.io 기사 게시 · 루브릭 4, 7: 완료 (10/11, https://www.hackster.io/ahind012/edgeguard-stop-forklift-accidents-before-they-happen-e07309)

표가 hackster 편집기에서 지원되지 않아 본문의 표 4개는 목록으로 옮겼습니다. 팀원(김기환) 추가와 회로도(Schematics)는 남아 있습니다.


1. hackster.io 로그인 → **New project**
2. 표지 이미지: `docs/img/demo_wait.png`(또는 `docs/img/mobility_map.png`)
3. Title / Elevator pitch: [hackster-article.md](hackster-article.md) 맨 위 제목과 첫 문단
4. Things used: 기사의 "Things used in this project" 목록
5. Story: [`submissions/hackster_story.md`](submissions/hackster_story.md)의 "## Story"부터 끝까지 붙여넣기 (링크와 이미지가 이미 GitHub 절대 주소로 바뀌어 있음)
6. Code: GitHub 저장소 링크 · Video: 2번에서 올린 YouTube 링크
7. 팀원(김기환) 추가 → **Publish** → 게시된 링크를 README의 Links에 추가

## 3-1. hackster 기사 갱신 (10/31 원고 준비 완료) · 루브릭 4, 7

원고가 v3.1 결과(현장 비교 1,000 에피소드 · 예외 상황 34,644건 충돌 0), 대규모 시험 차트 2장, 회로도 2장, 단말의 GO 확인 · 긴급제동 유지 설명으로 갱신됐습니다. 붙여넣기용 [`submissions/hackster_story.md`](submissions/hackster_story.md)는 `python tools/hackster_story.py`로 만들며, 링크 · 이미지는 GitHub 절대 주소, 표는 목록으로 바뀌어 있습니다.

1. hackster 로그인 → 기사 **Edit**
2. Story를 `hackster_story.md`의 "## Story"부터 끝까지로 교체(또는 바뀐 절만: 문제 1번 항목, 해결 한 문장, "When the network fails" 끝, Hardware build의 회로도, Results 전체)
3. **Schematics** 칸에 `docs/img/schematic_tag.png`, `docs/img/schematic_forklift.png` 업로드
4. **Team**에 김기환 추가(김기환 님 hackster 계정 필요)
5. **Save / Publish**

## 4. 공개 포럼 활동 · 루브릭 8

- ~~ACME 버그 2건 이슈 등록~~ 완료 (10/11): [#199](https://github.com/ankraft/ACME-oneM2M-CSE/issues/199) (HTTP Content-Type), [#200](https://github.com/ankraft/ACME-oneM2M-CSE/issues/200) (MQTT NameError). 초안: [forum/acme-issues.md](forum/acme-issues.md)
- oneM2M 개발자 커뮤니티(포럼/Discord)에 같은 문서 끝의 소개 글 게시(hackster 링크 포함)

## 5. 그 밖의 팀 작업

- 10/20까지: `docs/submissions/EdgeGuard_Interim_Report.pptx`를 팀 Discord 채널에 업로드
- ESP32 실물 보드 시연, 사용자 실험([user-study.md](ko/user-study.md))
