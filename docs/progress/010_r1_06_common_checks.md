# R1-06 — 공통 검증 명령

- 기록 번호: 010
- 상태: 완료
- 관련 로드맵: R1-06
- 완료 시각: 2026-08-25T05:30:39Z

## 작업한 내용

- Makefile의 format, lint, typecheck, unit, frontend, integration 명령을 실제 R1 소스와 연결했다.
- `make test`가 backend unit, React component, backend integration을 순서대로 실행하도록 확정했다.
- Vitest가 Playwright E2E 파일을 unit test로 잘못 수집하지 않도록 test 범위를 분리했다.
- 실제 설정, 임시 SQLite, FastAPI readiness를 연결하는 최소 integration test를 추가했다.

## 검증 결과

- `make check-format`: 통과
- `make lint`: 통과
- `make typecheck`: Python strict mypy와 TypeScript strict 모두 통과
- `make test-unit`: 13개 통과
- `make test-frontend`: 3개 통과
- `make test-integration`: 1개 통과
- `make test`: 전체 통과
- 앞선 R1-05의 Compose build, health, Chromium E2E, 정상 종료 결과와 함께 M0 구현 기준을 충족했다.

## 남은 문제와 결정

- FastAPI TestClient의 httpx2 전환 관련 deprecation 경고 1건이 남아 있으나 테스트 결과에는 영향이 없다.
- GitHub Actions와 OpenAPI schema check는 R3-07/R3-09에서 실제 구현한다.
- R1 종료 게이트 체크박스는 수정하지 않았다.

## 다음 작업

- R2-01에서 SQLite schema migration과 미래 schema version 거부를 구현한다.
