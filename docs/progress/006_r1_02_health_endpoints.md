# R1-02 — FastAPI health endpoint

- 기록 번호: 006
- 상태: 완료
- 관련 로드맵: R1-02
- 완료 시각: 2026-08-25T05:15:04Z

## 작업한 내용

- FastAPI application factory와 `GET /health/live`, `GET /health/ready`를 구현했다.
- liveness는 외부 준비 상태와 분리하고 readiness는 SQLite 연결과 다섯 필수 경로를 검사하도록 했다.
- readiness 실패 시 503과 검사별 상태를 반환하되 DB의 전체 경로나 내부 오류 문자열을 노출하지 않도록 했다.
- SQLite 연결에 foreign key와 busy timeout을 설정하는 공통 연결 함수를 추가했다.

## 검증 결과

- `ruff check`: 통과
- 전체 백엔드 `mypy --strict`: 통과
- liveness/readiness를 포함한 백엔드 단위 테스트: 12개 통과
- DB 실패 중에도 liveness가 200인 경우, 정상 readiness, DB 경로 redaction, 시작 후 경로 제거를 검증했다.

## 남은 문제와 결정

- 테스트 환경의 FastAPI TestClient가 향후 `httpx2` 전환 관련 Starlette deprecation 경고를 출력한다. 현재 테스트 동작에는 영향이 없으며 관련 패키지가 안정화될 때 lockfile과 함께 갱신한다.
- 실제 schema migration은 R2-01에서 추가한다. R1 readiness는 DB 연결 가능 여부만 검사한다.

## 다음 작업

- R1-03에서 같은 백엔드 패키지를 사용하는 worker 엔트리포인트와 SIGTERM 종료를 구현한다.
