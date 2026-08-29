# R5-04 — 인물과 화자 수정 API

- 기록 번호: 055
- 상태: 완료
- 관련 로드맵: R5-04
- 작업 브랜치: `feature/r5-04-speaker-edit-api`
- 기준 브랜치: `feature/r5-03-media-range-api`
- 선행 PR: #18 (R5-02 선행 PR #17)
- 완료일: 2026-08-29

## 작업한 내용

- `GET /api/persons`, `POST /api/persons`, `PATCH /api/persons/{person_id}`를 추가했다.
  표시 이름은 trim 후 1~100자로 검증하고 같은 이름의 서로 다른 person ID를 허용한다. 이름 수정은
  현재 person revision을 요구하며 성공할 때만 person revision을 한 번 증가시킨다.
- `PUT /api/recordings/{recording_id}/speakers/{local_speaker_id}`를 추가했다. 녹음 내 임시 화자를
  person에 연결하면 해당 local speaker가 primary인 모든 segment에 적용한다. overlap segment의
  diarization local ID, assignment 상태와 보조 화자 JSON은 변경하지 않는다.
- `PATCH /api/segments/{segment_id}/speaker`와 `PATCH /api/segments/speakers`를 추가했다.
  개별 또는 최대 500개의 segment person 판정만 바꾸며 diarization 결과는 보존한다. 일괄 요청은
  중복 ID를 거부하고 모든 segment가 요청한 한 recording에 속하는지 확인한다.
- 화자와 segment 쓰기는 recording revision을 요구한다. SQLite `BEGIN IMMEDIATE` 안에서 revision,
  recording/person/segment 범위를 검증하고 모든 변경과 audit event를 함께 commit한다. 일괄 수정도
  recording revision을 정확히 한 번만 증가시킨다.
- stale revision은 공통 `409 REVISION_CONFLICT`와 현재 revision으로, 없는 recording/person/
  local speaker/segment는 공통 404로, 중복·500개 초과·recording 혼합 요청은 공통 422로 응답한다.
- `person_id`가 있으면 해당 person에, 명시적 null이면 사용자가 선택한 “알 수 없음”에 연결한다.
  두 경우 모두 `speaker_source = manual`, `speaker_score = null`로 저장해 기존 auto 판정을 덮어쓴다.
- person 표시 이름을 바꾼 직후 녹음 상세 API가 `persons` 원장을 join해 최신 이름을 반환한다.
  segment의 cached speaker name이 이전 값이어도 공개 응답은 person 원장의 이름을 우선한다.
- person 생성·이름 수정, 녹음 화자 전체 연결, 개별·일괄 segment 연결을 모두 audit event로 남긴다.
  audit details에는 ID, revision, 수정 개수만 기록하고 transcript 본문이나 person 표시 이름은 넣지
  않는다.
- 녹음 상세 segment 응답에 판정 출처와 점수를 추가하고, 새 endpoint의 OpenAPI snapshot과 생성
  TypeScript 타입을 갱신했다.

## 자동 검증 결과

- Ruff format/lint와 `git diff --check`: 통과
- mypy strict: 77개 source 파일 통과
- Prettier, ESLint, TypeScript strict: 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit: 297개 통과
  - person 생성/목록/trim/길이/중복 이름/이름 수정/person revision 충돌
  - 녹음 화자 전체 연결, 개별 segment 연결, 명시적 unknown과 manual 우선
  - overlap 보조 화자와 diarization local ID 보존
  - 최대 500개·중복 없는 일괄 수정과 recording revision 단일 증가
  - 다른 recording 혼합 거부, 대상 404, recording revision 충돌 시 무변경
  - audit 삽입 실패 transaction rollback, transcript/name redaction, 최신 person 이름 조회
- backend integration: 15개 통과
- frontend unit: 9개 통과
- Docker Compose browser smoke: pipeline/health 2개와 worker 재시작 보존 1개 통과

## 비범위와 다음 작업

- 화자 검토 React 화면은 R5-05, revision 충돌 UX는 R5-06에서 구현한다.
- 수정 후 transcript artifact 무효화·재렌더, summary 무효화와 후속 job 등록은 계획대로 R5-08에
  남겼다. 이번 API는 DB 원장과 revision·audit 계약만 갱신한다.
- 이번 변경은 GPU 모델을 다시 실행하지 않으므로 GPU 검증은 수행하지 않았다.
- 비공개 transcript 본문, 원본 절대 경로와 credential은 테스트 출력과 이 문서에 기록하지 않았다.
