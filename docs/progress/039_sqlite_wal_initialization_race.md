# SQLite WAL 초기화 경쟁 수정

- 기록 번호: 039
- 상태: 완료
- 관련 로드맵: 공통 Definition of Done, R4 M2 회귀 검증
- 작업 브랜치: `fix/sqlite-wal-initialization-race`
- 완료 시각: 2026-08-26T23:20:41Z

## 발견한 문제

- R4-08 착수 후 전체 backend 회귀에서 같은 content hash를 동시에 등록하는 기존 테스트가
  `PRAGMA journal_mode = WAL`의 `database is locked` 오류로 실패했다.
- 이전 R4 progress에도 일시 실패로 기록됐지만 이번 검증에서는 전체 실행, 대상 재실행, 두 번째
  대상 재실행까지 3회 연속 재현돼 완료 게이트 blocker로 판정했다.
- 모든 새 연결이 현재 journal mode를 확인하지 않고 WAL 설정을 다시 실행했고, 빈 DB에 두 연결이
  동시에 들어오면 WAL 전환에 필요한 lock을 서로 경쟁하는 것이 원인이었다.

## 작업한 내용

- SQLite 연결 시 현재 journal mode가 이미 WAL이면 쓰기 성격의 WAL 전환 PRAGMA를 생략한다.
- 초기 DB에서 WAL 전환이나 설정이 `locked`/`busy`로 실패하면 연결을 닫고 최대 6회 짧은 지수
  backoff 후 새 연결로 다시 초기화한다.
- lock 경쟁이 아닌 `OperationalError`는 숨기지 않고 즉시 호출자에게 전달한다.
- 동일 hash 동시 등록 회귀를 서로 다른 빈 DB 10개에 반복해 recording과 job이 정확히 하나만
  만들어지는 계약을 고정했다.

## 자동 검증 결과

- SQLite 동시 등록 반복: 10개 시나리오 통과
- repository 전체: 12개 통과
- migration/job 회귀: 10개 통과
- backend unit/integration 전체: 208개 통과
- 기본 fake Compose api/worker/web 동시 시작과 health: 통과
- Playwright readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- Ruff format/lint, mypy strict, `git diff --check`: 통과

FastAPI TestClient 전체 검증은 샌드박스 밖에서 실행했다. 기존 httpx2 전환 경고 1건은 현재
runtime 실패가 아니다.

## 알려진 조건과 다음 작업

- 이 retry는 SQLite 연결 초기화의 짧은 lock 경쟁만 다룬다. stale job 회수나 장시간 DB lock의
  사용자 복구 정책은 R9 범위다.
- 보존한 R4-08 변경을 `feature/r4-08-fixed-audio-evaluation` 브랜치에 복원하고 실제 고정 음성
  평가 구현을 계속한다.
