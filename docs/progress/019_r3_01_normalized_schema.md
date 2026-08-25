# R3-01 — 정규화된 내부 schema

- 기록 번호: 019
- 상태: 완료
- 관련 로드맵: R3-01
- 완료 시각: 2026-08-25T06:01:46Z

## 작업한 내용

- 공급자 원시 응답과 분리된 schema version 1의 recording 상태, segment, transcript, classification, 회의 summary Pydantic 모델을 추가했다.
- segment 시간 범위, 임시 화자 ID, 빈 텍스트, UUID, SHA-256, revision, 분류 confidence를 검증하도록 했다.
- 설정에서 허용한 category만 classification 결과로 사용할 수 있는 검증 경계를 추가했다.
- SQLite schema version을 2로 올리고 segments 테이블, category reason, job input revision과 settings fingerprint를 추가했다.
- 같은 recording, job kind, input revision, settings fingerprint의 성공 결과가 중복되지 않도록 DB 제약을 추가했다.
- 기존 version 1 DB가 순차적으로 version 2로 업그레이드되도록 유지했다.

## 검증 결과

- Ruff: 통과
- mypy strict: 통과
- schema 및 migration 단위 테스트: 11개 통과
- 빈 DB 최신 schema, migration 재실행, 미래 schema 거부, version 1 업그레이드: 통과
- 잘못된 시간, 화자 ID, 빈 텍스트, 상태, category 거부: 통과

## 남은 문제와 결정

- R3에서는 fixture가 제공하는 회의 summary 최소 구조만 정규화한다. 범주별 상세 summary schema는 로드맵 R8에서 확장한다.
- 모델 공급자의 원시 응답 타입은 새 schema나 DB에 포함하지 않았다.

## 다음 작업

- R3-02에서 fixture manifest와 콘텐츠 SHA-256을 사용하는 결정적 fake speech/document 어댑터를 구현한다.
