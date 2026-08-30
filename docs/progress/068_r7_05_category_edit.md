# R7-05 범주 수동 수정 API·GUI

## 작업 관계

- 로드맵 R7-05의 범주 수정 API/GUI를 구현했다.
- base는 `main`이며 선행·후속 PR이 없는 독립 PR이다.
- R6-05는 `pyannote/embedding` 접근 승인과 같은 사람·다른 사람·애매한 사람의 비공개
  평가 표본이 없어 계속 차단 상태다. 평가 근거 없이 threshold/margin을 정하거나 자동 확정을
  활성화하지 않았다.
- R6 평가와 R7 개발은 병행할 수 있으므로 R6-05와 독립적인 R7-05를 진행했다.

## 구현 결과

- SQLite schema를 v11로 올리고 기존 적용 범주와 마지막 자동 제안을 분리했다.
  - `category`: 실제 적용 범주
  - `automatic_category`: 마지막 자동 분류 제안
  - `category_source`: `auto`, `manual`, 또는 미분류 `NULL`
  - 기존 분류 데이터는 자동 출처로 이관하고 미분류 데이터는 `NULL`을 유지한다.
- `PATCH /api/recordings/{recording_id}/category`를 추가했다.
  - 허용 범주, 분류 완료 여부, 동일 값, expected revision을 검증한다.
  - classify/render/summarize 활성 작업을 구분해 `409`로 거부한다.
  - 범주·revision 갱신, render job 등록, `recording_category_updated` 감사를 한 transaction에서
    처리한다.
  - 감사 기록에는 변경 전후 범주와 revision만 저장한다.
- 상세 API는 `allowed_categories`, `category_source`, `automatic_category`를 반환한다.
- 수동 범주는 STT 재수행과 이후 자동 재분류보다 우선하며 자동 제안·confidence·reason만 새로
  갱신된다.
- 현재 revision과 다른 summary는 상세 API에서 즉시 제외된다. 이전 summary가 있으면 render
  완료 뒤 새 revision의 summary job을 등록한다.
- transcript JSON에 `classification_source`를 추가하고 Markdown에 적용 범주 출처를 렌더한다.
  수동 범주는 가짜 confidence를 만들지 않고 `null`/`N/A`와 사용자 선택 고정 근거를 사용한다.
- worker 시작 시 Markdown reconciliation도 수동 출처 계약과 범주만 바뀐 revision의 기존
  segment를 올바르게 복구한다.
- 상세 화면에 현재 적용 범주·출처, 자동 제안·confidence·reason, 서버 허용 목록 기반 native
  select와 저장 상태를 추가했다. 같은 값 저장을 막고 revision 충돌은 최신 내용을 다시 불러오며,
  처리 중 충돌·422·네트워크 실패에 다음 행동을 안내한다.

## 검증 결과

- 포맷
  - `.venv/bin/ruff format --check backend`: 통과
  - `npm --prefix frontend run format:check`: 통과
- lint
  - `.venv/bin/ruff check backend`: 통과
  - `npm --prefix frontend run lint`: 통과
- typecheck
  - `.venv/bin/mypy`: 통과
  - `npm --prefix frontend run typecheck`: 통과
- API schema
  - `PYTHONPATH=backend .venv/bin/python -m app.openapi --check`: 통과
  - `npm --prefix frontend run api:types:check`: 통과
- 테스트
  - `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit`: 321 passed
  - `PYTHONPATH=backend .venv/bin/pytest backend/tests/integration`: 25 passed
  - `npm --prefix frontend test`: 25 passed
  - `./scripts/compose-smoke.sh`: 통과
    - Compose 기반 Playwright: 3 passed
    - worker 재시작 후 보존 재검증: 1 passed
- `git diff --check`: 통과
- 호스트에 `uv` 실행 파일이 없어 `make check-format`, `make lint`, `make typecheck`,
  `make api-schema-check`, `make test-unit`, `make test-integration`은 같은 `.venv`와 npm 명령을
  직접 실행했다. `compose-smoke`는 스크립트가 Compose 안에서 정식 `make test-e2e`를 실행한다.

검증에는 v10→v11 이관과 제약, PATCH 정상/오류/활성 작업 충돌, 감사 실패 rollback, summary
stale/후속 job, JSON·Markdown revision·범주·출처 일치, reconciliation, 수동 범주의 재전사·자동
재분류 우선순위, UI 성공·revision 충돌·422·네트워크 오류와 접근 가능한 label/키보드 조작이
포함된다.

## GPU 검증

이번 변경은 SQLite schema, HTTP API, transcript renderer/reconciliation, React 상세 화면만
수정한다. CUDA·NVIDIA dependency, GPU container/runtime, GPU device 선택, GPU에서 실행되는 worker
모델 경로를 사용하거나 변경하지 않으므로 실제 NVIDIA/GPU 검증은 필요하지 않다.

R6-05의 실제 embedding 보정과 표본 평가는 별도 GPU·비공개 평가 자료가 준비된 뒤 수행해야 하며,
이번 결과로 대체하지 않는다.

## 비범위

- R6-05 threshold/margin 보정과 자동 확정 활성화
- R6-06 실제 화자 회귀 평가
- R7-06 분류 fixture 평가 확장과 R7 종료 게이트 갱신
- R8 자동/수동 summary 정책과 summary 경로 이동·이전 파일 정리
- 외부 LLM 공급자 호출 또는 실제 transcript 외부 전송
