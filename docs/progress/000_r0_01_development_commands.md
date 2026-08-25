# R0-01 — 개발 명령 진입점

- 기록 번호: 000
- 상태: 완료
- 관련 로드맵: R0-01
- 완료 시각: 2026-08-25T05:07:53Z

## 작업한 내용

- Python 3.11, uv, `uv.lock`을 Python 패키지 관리 기준으로 고정했다.
- Node.js 24, npm, `frontend/package-lock.json`을 프런트엔드 패키지 관리 기준으로 고정했다.
- 루트 `Makefile`에 format, lint, typecheck, OpenAPI, unit, frontend, integration, E2E, Compose smoke, model eval 명령 이름을 예약했다.
- 실제 `.env`, 런타임 데이터, 비밀값, 빌드 결과가 Git에 포함되지 않도록 `.gitignore`를 확장했다.
- README에 개발 도구와 공통 명령을 기록했다.

## 검증 결과

- `uv lock --check`: 통과
- `npm --prefix frontend install --package-lock-only --ignore-scripts`: 통과
- 모든 Make target에 대한 `make -n <target>` 구문 검사: 통과
- `model-eval`은 R4 이전에 성공을 가장하지 않고 미지원 종료 코드를 반환하도록 예약했다.

## 남은 문제와 결정

- 시스템 전역에 uv를 설치하지 않았으므로 현재 구현 세션은 `/tmp`에 받은 uv 실행 파일을 사용한다. 신규 개발자는 README에 따라 uv를 설치해야 한다.
- 실제 검사 대상 소스와 테스트는 R1~R3 작업에서 명령에 연결한다.

## 다음 작업

- R0-02에서 FFmpeg로 생성한 비민감 m4a fixture와 fake 기대 결과를 추가한다.
