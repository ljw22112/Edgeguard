# 공개 · 게시 체크리스트 (팀 작업)

[← README](../README.ko.md)

계정 로그인이 필요해 사람이 마지막 클릭을 해야 하는 일들입니다. 순서대로 하면 루브릭 4 · 5 · 6 · 7 · 8번 점수가 오릅니다.

## 1. 저장소 공개 · 루브릭 6, 7: 완료 (10/11)

전체 커밋 이력에서 비밀번호 · 토큰 · 키 파일 · 공인 IP · ssh 접속 정보를 검사했고 나온 것은 없습니다. 데모용 인증서와 비밀번호는 실행할 때 `.certs/`에 생성되며, 이 폴더는 커밋되지 않습니다.

1. ~~Danger Zone → Make public~~ 완료
2. (선택) Packages → `edgeguard-mobius`, `edgeguard-mec` → Package settings → **Change visibility → Public**: `docker compose`가 로그인 없이 이미지를 받을 수 있게 됩니다.
3. 저장소 첫 화면 오른쪽 About 톱니바퀴: Description에 `Worker–forklift collision prediction on oneM2M + ETSI MEC (2026 oneM2M Hackathon)`, Topics에 `onem2m`, `etsi-mec`, `iot`, `edge-computing`, `safety`, `acme-cse`, `mobius` 입력

## 2. 영상 업로드 · 루브릭 5

- 파일: `results/edgeguard_final.mp4`(2분 34초, 자막 `results/edgeguard_final.srt`)
- 내레이션 녹음(선택): [video-script.md](video-script.md) 대본을 읽어 녹음한 뒤 문서의 ffmpeg 명령으로 합칩니다.
- YouTube 업로드: 공개 또는 일부 공개, 자막 파일(.srt)도 함께 올립니다.
- 제목 예시: `EdgeGuard – Forklift collision prediction with oneM2M and ETSI MEC (2026 oneM2M Hackathon)`

## 3. hackster.io 기사 게시 · 루브릭 4, 7

1. hackster.io 로그인 → **New project**
2. 표지 이미지: `docs/img/demo_wait.png`(또는 `docs/img/mobility_map.png`)
3. Title / Elevator pitch: [hackster-article.md](hackster-article.md) 맨 위 제목과 첫 문단
4. Things used: 기사의 "Things used in this project" 목록
5. Story: 기사 본문의 "## Story"부터 끝까지 붙여넣기. 이미지(`docs/img/*.png`)는 해당 위치에 업로드합니다. `../edgeguard/...` 같은 상대 링크는 `https://github.com/ljw22112/Edgeguard/blob/main/...`로 바꾸면 됩니다.
6. Code: GitHub 저장소 링크 · Video: 2번에서 올린 YouTube 링크
7. 팀원(김기환) 추가 → **Publish** → 게시된 링크를 README의 Links에 추가

## 4. 공개 포럼 활동 · 루브릭 8

- ACME 버그 2건 이슈 등록: [forum/acme-issues.md](forum/acme-issues.md)의 초안을 https://github.com/ankraft/ACME-oneM2M-CSE/issues/new 에 붙여넣기
- oneM2M 개발자 커뮤니티(포럼/Discord)에 같은 문서 끝의 소개 글 게시(hackster 링크 포함)

## 5. 그 밖의 팀 작업

- 10/20까지: `docs/submissions/EdgeGuard_Interim_Report.pptx`를 팀 Discord 채널에 업로드
- ESP32 실물 보드 시연, 사용자 실험([user-study.md](ko/user-study.md))
