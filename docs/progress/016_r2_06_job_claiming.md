# R2-06 — 단일 worker job claim

- 기록 번호: 016
- 상태: 완료
- 관련 로드맵: R2-06
- 완료 시각: 2026-08-25T05:37:36Z

## 작업한 내용

- 실행 가능한 가장 오래된 queued job 하나를 `BEGIN IMMEDIATE` 안에서 running으로 점유하는 연산을 구현했다.
- claim 시 attempts, locked_at, updated_at을 기록하고 과거 오류를 초기화하도록 했다.
- 성공, 영구 실패, 예약 재시도, SIGTERM 반환을 위한 complete/fail/release 연산을 구현했다.
- 재시도는 attempts를 지우지 않고 다음 claim에서 증가시키도록 했다.
- running이 아닌 job을 완료·실패·반환하려는 잘못된 호출을 거부하도록 했다.

## 검증 결과

- `ruff check`: 통과
- 전체 백엔드 `mypy --strict`: 통과
- 두 thread 동시 claim에서 같은 job을 한 worker만 점유: 통과
- 성공 후 attempts와 unlocked 상태 보존: 통과
- 실패 후 재시도에서 attempts 2로 증가: 통과
- release 후 queued 복귀 및 시도 이력 보존: 통과
- job claim 단위 테스트 4개 통과

## 남은 문제와 결정

- 비정상 SIGKILL 뒤 stale lock 회수는 R9의 운영 복구 범위다. 현재 SIGTERM 경로는 실행 중 job을 명시적으로 반환한다.
- R2 handler는 다음 통합 작업에서 성공/실패를 선택할 수 있는 최소 함수로 연결한다.

## 다음 작업

- R2-07에서 scanner, ffprobe, hash, DB 등록, job claim을 실제 fixture와 임시 디렉터리로 통합한다.
