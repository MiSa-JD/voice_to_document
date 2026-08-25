# R0~R3 — 로드맵 종료 게이트 재검증

- 기록 번호: 029
- 상태: 완료
- 관련 로드맵: R0 종료 게이트, R1 M0, R2 M0.5, R3 M1
- 완료 시각: 2026-08-25T06:42:51Z

## 검증 목적

- `docs/02_development_roadmap.md`의 체크박스와 진행 현황이 실제 저장소 상태를 반영하는지 다시 확인한다.
- 기존 `docs/progress/000`~`028` 기록만 신뢰하지 않고 현재 코드의 품질 검사, 테스트, Compose, 브라우저 흐름을 다시 실행한다.
- 현재 환경에서 증명하지 못한 실제 WhisperX/pyannote 단계는 완료로 추정하지 않는다.

## 저장소와 기존 증거 확인

- R0의 단일 명령 진입점, `uv.lock`, `frontend/package-lock.json`, 비민감 합성 m4a와 기대 JSON이 존재한다.
- `docs/03_development_environment.md`에 fake 개발 장비, 향후 Linux RTX 3060 12GB 평가 장비, `HF_TOKEN` 관리 주체, 외부 LLM 전송 허용 방향과 최종 결정 기한이 기록되어 있다.
- `.env`는 `.gitignore`에 포함되어 있고 Git 추적 대상이 아니며, `.env.example`만 추적된다.
- R1~R3 구현과 테스트, OpenAPI snapshot, 프런트엔드 생성 타입, CI workflow, Compose smoke 스크립트가 존재한다.
- 검증 시작 시 Git 작업 트리는 깨끗했다.

## 현재 코드 재검증 결과

현재 셸에는 `uv` 실행 파일이 `PATH`에 없어 `make check-format lint typecheck api-schema-check test`는 첫 명령에서 시작하지 못했다. 이는 코드 실패와 구분해 기록하고, 이미 설치된 저장소 `./.venv` 실행 파일과 동일한 npm script를 직접 호출해 아래 검증을 수행했다.

- Ruff format: 39개 파일 통과
- Ruff lint: 통과
- mypy strict: 38개 source 파일 통과
- Prettier: 통과
- ESLint: 통과
- TypeScript strict typecheck: 통과
- OpenAPI JSON snapshot drift: 통과
- OpenAPI 기반 TypeScript 생성 타입 drift: 통과
- backend unit/integration 전체: 78개 통과
- React Testing Library: 8개 통과

백엔드 테스트에서는 FastAPI TestClient의 향후 httpx 호환성에 관한 deprecation warning 1건이 있었지만 테스트 실패나 현재 runtime 오류는 없었다.

## Compose와 브라우저 재검증 결과

`./scripts/compose-smoke.sh`를 실행해 다음을 다시 확인했다.

- `api`, `worker`, `web` 이미지 build: 통과
- 세 서비스 health와 Compose 기동: 통과
- 브라우저 readiness/404 구분: Playwright Chromium 1개 통과
- fixture 입력부터 dashboard/detail transcript/category/summary 표시: Playwright Chromium 1개 통과
- worker 재시작 뒤 DB/API/UI 결과 보존: Playwright Chromium 1개 통과
- smoke 종료 시 Compose 서비스와 전용 임시 데이터 디렉터리 정리: 통과

이 smoke는 fake 어댑터만 사용하며 GPU, `HF_TOKEN`, 외부 LLM API 키를 사용하지 않았다.

## 종료 게이트 판정

### R0 — `DONE`

- 개발 명령 체계와 lockfile, 비민감 fixture, 기대 결과를 확인했다.
- GPU 환경은 “현재 미확보, R4에서 Linux RTX 3060 검증 예정”으로 명확히 기록되어 있다.
- pyannote 토큰과 LLM 개인정보 정책의 소유자는 사용자로 기록되어 있다.
- 실제 GPU runtime 결정은 R4 전, 외부 LLM 공급자 결정은 R7 전으로 기한이 기록되어 있다.

### R1 — `DONE`

- Compose 세 서비스의 시작·health·종료와 브라우저 readiness를 재검증했다.
- 잘못된 설정의 시작 실패는 backend 설정/health 테스트에 포함되어 통과했다.
- Python/TypeScript format, lint, typecheck가 모두 통과했다.
- `.env`와 비밀값이 Git에 추적되지 않음을 확인했다.

### R2 — `DONE`

- 안정 파일 판정, 손상 파일 거부, 스트리밍 해시 중복 방지, 원자적 job claim 관련 테스트가 모두 통과했다.
- 같은 콘텐츠의 중복 job 방지와 worker 재시작 뒤 상태 보존을 integration/Compose 흐름에서 확인했다.
- 입력 인수 시나리오 1~4의 자동 검증이 현재 전체 backend 테스트에 포함되어 통과했다.

### R3 — `DONE`

- fixture가 `DISCOVERED`에서 `COMPLETED`까지 진행하고 네 artifact를 생성하는 fake 수직 흐름을 확인했다.
- dashboard/detail의 상태, transcript, category, summary와 worker 재시작 보존을 실제 브라우저에서 확인했다.
- 실패 주입과 재시도 시 job/artifact 중복 방지 테스트가 통과했다.
- OpenAPI와 프런트엔드 타입이 일치했다.
- CI workflow가 로컬과 같은 Makefile 진입점을 호출하고 real AI 비밀값이나 GPU를 요구하지 않음을 확인했다.

### R4 이후 — 미완료

- R4의 실제 WhisperX `large-v3`, alignment, pyannote diarization과 Linux CUDA runtime은 이 macOS 개발 환경에서 검증하지 않았다.
- 따라서 R4 체크박스는 채우지 않고, 진행 현황은 Linux NVIDIA GPU runtime과 실제 모델 의존성 검증을 기다리는 `BLOCKED`로 기록했다.
- R5~R10은 선행 단계가 완료되지 않았으므로 `NOT STARTED`를 유지했다.

## 후속 조치

- 로컬에서 Makefile 공통 검증 명령을 그대로 재현하려면 README의 전제에 따라 `uv`를 설치하거나 `PATH`에 연결해야 한다.
- Linux NVIDIA GPU 장비가 준비되면 R4-01의 driver, NVIDIA Container Toolkit, CUDA 접근 smoke부터 시작한다.
- GitHub Actions의 원격 실행 성공 여부는 저장소 push 이후 별도로 확인한다.
