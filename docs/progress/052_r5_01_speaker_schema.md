# R5-01 — 화자 DB schema

- 기록 번호: 052
- 상태: 완료
- 관련 로드맵: R5-01
- 작업 브랜치: `feature/r5-01-speaker-schema`
- 기준 커밋: `a8cbbb5`
- 완료일: 2026-08-29

## 작업한 내용

- SQLite schema를 v5로 올리고 실제 인물을 ID로 구분하는 `persons` 테이블을 추가했다.
  `display_name`은 비어 있을 수 없지만 unique로 제한하지 않아 같은 표시 이름을 허용하며,
  revision과 생성·수정 시각을 함께 저장한다.
- `(recording_id, local_speaker_id)`를 기본 키로 사용하는 `recording_speakers`를 추가했다.
  nullable person 연결, `manual`/`auto`/`unresolved` 판정 출처, 0~1 선택 점수, revision과
  생성·수정 시각을 RDB 원장으로 관리한다.
- v4 segment의 일반 배정과 overlap JSON에서 발견되는 임시 화자를 중복 없이
  `recording_speakers`에 backfill했다. person 원장이 없던 기존 `person_id`로 person을 임의 생성하지
  않고 null로 이전했으며, segment의 텍스트·시간 범위·화자명·source·score·revision은 보존했다.
- `segments.person_id`를 `persons.id` 외래키로 연결했다. person 삭제 시 segment와 원문은 유지하고
  person 참조만 null로 바뀐다.
- 새 transcript 저장 경로가 primary 및 overlap 임시 화자를 `recording_speakers`에 멱등 등록하게
  했다. 기존 화자 판정 행이 있으면 덮어쓰지 않는다.
- `speaker_embeddings`에는 벡터 본문 대신 person, recording/local speaker, segment 출처,
  model fingerprint, vector store, collection, vector key, 활성/무효화 상태와 시각만 저장한다.
  복합 외래키로 segment와 녹음 내 화자 출처가 서로 일치하도록 보장한다.
- VDB point ID 계약은 `vector_key = speaker_embeddings.id` check와 unique 제약으로 고정했다.
  VDB 인덱스가 없어져도 RDB의 segment 시간 범위, 수동 person 판정과 원본 음성을 이용해 다시
  생성할 수 있으며 SQLite를 판정과 metadata의 원장으로 유지한다.
- 공개 API와 OpenAPI 계약은 변경하지 않았고 외부 VDB 의존성도 추가하지 않았다.

## 자동 검증 결과

- Ruff format/lint와 `git diff --check`: 통과
- mypy strict: 71개 source 파일 통과
- Prettier, ESLint, TypeScript strict: 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit: 265개 통과
  - 빈 DB v5 migration, v4 데이터 보존/backfill, migration 재실행 멱등성, future schema 보호
  - 동일 person 표시 이름, person 삭제 시 segment null 처리, source/score/revision/FK/중복 제약
  - embedding source, point ID, vector key, 활성/무효화 상태 제약
  - 실제 pipeline의 primary/overlap 임시 화자 원장 등록
- backend integration: 15개 통과
- frontend unit: 9개 통과

## 비범위와 다음 작업

- 실제 VDB 제품과 collection 생성, embedding 모델·차원·dtype, 생성·검색·재색인 로직은 R6-01에서
  확정한다.
- 대표 구간 선택과 클립 생성은 R5-02, media range API는 R5-03, person 및 화자 수정 API는
  R5-04 범위다.
- 이 작업은 DB 전용이므로 GPU 및 실제 모델 검증은 수행하지 않았다.
- 비공개 transcript 본문, 원본 절대 경로와 credential은 테스트 출력과 이 문서에 기록하지 않았다.
