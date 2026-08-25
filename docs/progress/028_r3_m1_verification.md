# R3 — M1 가짜 AI 수직 흐름 최종 검증

- 기록 번호: 028
- 상태: 완료
- 관련 로드맵: R3 종료 게이트 — M1
- 완료 시각: 2026-08-25T06:34:14Z

## 작업한 내용

- R2의 안전한 입력 등록 위에 정규화 schema, fake speech/document, 상태 전이, 원자적 artifact, API, React, OpenAPI 타입, Compose E2E, CI를 연결했다.
- 완료 fixture가 실제 Compose worker에서 DISCOVERED부터 COMPLETED까지 처리되는 전체 수직 흐름을 닫았다.
- 화자 검토 fixture는 SPEAKER_REVIEW에서 멈추고 분류·요약 job을 만들지 않도록 고정했다.
- 모든 Python 패키지는 저장소 `./.venv`를 통해 실행했고 시스템 Python 영역에는 설치하지 않았다.
- R3 작업별 결과는 `019`부터 `027`까지 순서대로 기록했다.

## 최종 검증 결과

- backend Ruff format/check: 통과, 39개 파일
- backend mypy strict: 통과, 38개 source 파일
- frontend Prettier, ESLint, TypeScript strict: 통과
- OpenAPI JSON snapshot drift: 통과
- OpenAPI 기반 TypeScript 생성 타입 drift: 통과
- backend unit: 71개 통과
- backend integration: 7개 통과
- React Testing Library: 8개 통과
- Vite production build: 통과
- Compose build와 api/worker/web health: 통과
- 실제 Playwright Chromium service status/dashboard/404: 통과
- 실제 fixture dashboard/detail transcript/category/summary: 통과
- worker 재시작 후 recording/job/artifact/API/UI 보존: 통과
- 완료 recording의 jobs 3개 모두 succeeded, artifacts 4개 유지: 통과
- Compose 종료 후 남은 container: 0개
- `git diff --check`: 통과
- progress 문서 번호: 000부터 028까지 연속

## 알려진 경고와 남은 조건

- FastAPI TestClient가 Starlette의 향후 httpx 호환성 변경에 대한 deprecation warning 1건을 출력하지만 현재 테스트 실패나 runtime 오류는 없다.
- GitHub Actions workflow 자체의 원격 실행 결과는 repository push 이후 확인할 수 있다. workflow YAML과 로컬 진입점은 검증했다.
- 현재 개발 장비는 macOS Apple Silicon이며 R4의 실제 WhisperX/pyannote 검증에 필요한 Linux NVIDIA GPU 환경이 아니다.
- R4 진입 전 Linux RTX 3060 12GB 장비, NVIDIA driver/CUDA 호환 runtime, 실제 모델 다운로드와 HF token 전달을 준비해야 한다.
- 기존 `/tmp/voice_to_document_r2.GDQpEf`의 합성 fixture와 DB는 삭제하지 않았다.

## 종료 게이트 기록 원칙

- R2와 R3 종료 게이트를 뒷받침하는 구현·자동 검증 증거는 progress 문서에 기록했다.
- `docs/02_development_roadmap.md`는 수정하지 않았으며 종료 게이트 체크박스는 모두 원문 그대로 유지했다.

## 다음 작업

- Linux NVIDIA GPU 환경이 준비되면 R4-01 GPU/driver/CUDA 사전 검증부터 시작한다.
- 환경이 준비되기 전에는 실제 모델 패키지와 모델 파일을 현재 Mac 또는 project runtime에 설치하지 않는다.
