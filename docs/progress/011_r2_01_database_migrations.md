# R2-01 — SQLite schema와 migration

- 기록 번호: 011
- 상태: 완료
- 관련 로드맵: R2-01
- 완료 시각: 2026-08-25T05:32:01Z

## 작업한 내용

- 별도 migration 프레임워크 없이 `schema_migrations`와 순차 SQL 목록을 구현했다.
- 첫 schema에 recordings, jobs, artifacts, audit_events 테이블과 필요한 index/제약을 추가했다.
- SQLite 연결마다 foreign key, busy timeout, WAL, NORMAL synchronous, Row factory를 적용했다.
- 현재 코드보다 미래 버전인 DB는 `FutureSchemaError`로 중단하고 덮어쓰지 않도록 했다.
- 상태, 양수 크기·길이, revision, 활성 job 중복을 DB 제약으로 보호했다.

## 검증 결과

- `ruff check`: 통과
- 전체 백엔드 `mypy --strict`: 통과
- 빈 DB 최신 schema 생성: 통과
- 같은 migration 두 번 실행: 통과
- 미래 schema version 거부: 통과
- 잘못된 recording DB 제약 거부: 통과
- migration 단위 테스트 4개 통과

## 남은 문제와 결정

- segments와 pipeline fingerprint 필드는 R3 migration에서 추가한다.
- API와 worker 시작 시 migration 실행 연결은 recording 저장 연산과 함께 R2에서 적용한다.

## 다음 작업

- R2-02에서 recording 등록과 최초 transcribe job 생성을 하나의 트랜잭션으로 구현한다.
