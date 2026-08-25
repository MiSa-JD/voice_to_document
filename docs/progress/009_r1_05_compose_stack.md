# R1-05 — 세 컨테이너 Compose 연결

- 기록 번호: 009
- 상태: 완료
- 관련 로드맵: R1-05
- 완료 시각: 2026-08-25T05:29:32Z

## 작업한 내용

- Python 3.11/uv 기반 공용 backend 이미지에서 api와 worker를 다른 command로 실행하도록 구성했다.
- Node.js 24 build와 unprivileged Nginx runtime을 사용하는 web 이미지를 구성했다.
- Nginx가 `/api/*`와 `/health/*`를 API로 전달하고 클라이언트 경로만 React HTML로 fallback하도록 했다.
- 호스트에는 web의 `127.0.0.1:8000`만 공개했다.
- API는 입력·결과 디렉터리를 읽기 전용, app-data를 쓰기 가능으로 mount하고 worker만 결과 디렉터리에 쓰도록 분리했다.
- `.env`에서 컨테이너 내부 루트를 변경하면 설정과 volume target이 함께 변경되도록 연결했다.
- 실제 Chromium Playwright health/404 smoke를 추가했다.

## 검증 결과

- `docker compose config --quiet`: 통과
- api, worker, web 이미지 build: 통과
- 세 서비스 `healthy`/기동 상태: 통과
- 브라우저 공개 경로의 `/health/live`, `/health/ready`: 200
- 존재하지 않는 `/api` 경로: 404 JSON이며 React HTML로 변환되지 않음
- 존재하지 않는 client 경로: React 404 화면으로 fallback
- 잘못된 `APP_DATA_DIR=/missing`: 변수명을 포함한 시작 실패
- worker SIGTERM: stop 요청과 정상 종료 구조화 로그 확인
- Playwright Chromium health/404 E2E: 1개 통과
- `docker compose down`: 정상 종료

## 남은 문제와 결정

- in-app Browser runtime에는 사용 가능한 브라우저가 없어 해당 수동 제어 방식은 실행하지 못했다. 같은 사용자 흐름은 설치된 Playwright Chromium으로 실제 렌더링 검증했다.
- backend 이미지의 FFmpeg 설치층이 크지만 R2 ffprobe와 이후 미디어 처리에 바로 필요하므로 유지한다.

## 다음 작업

- R1-06에서 Makefile의 format, lint, typecheck, backend/frontend test 진입점을 전체 소스에 대해 검증한다.
