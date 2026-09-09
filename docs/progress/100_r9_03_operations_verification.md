# R9-03 운영 현황 API·대시보드와 통합 검증

작성일: 2026-09-10. 구현·로컬 검증: 2026-09-09.
브랜치: `feature/r9-03-operations-visibility → feature/r9-02-job-retry-ui`.
스택: [PR #56](https://github.com/MiSa-JD/voice_to_document/pull/56) → [PR #57](https://github.com/MiSa-JD/voice_to_document/pull/57) → 이 작업.

녹음 목록에 operations를 추가했다. 전체 DB의 queued_jobs/running_jobs,
needs_speaker_review 기준 review_recordings, 현재 FAILED 녹음 기준 failed_recordings,
성공·실패로 종료한 job의 마지막 updated_at인 last_job_finished_at을 한 read snapshot으로 조회한다.
최근 50개나 목록 필터에 한정하지 않고 backoff queued도 포함한다. 종료 이력이 없으면 null이다.

대시보드는 작업과 녹음 단위를 나눠 표시하고 최근 처리 시각을 브라우저 로컬 시간으로 보여준다.
목록 밖에 활성 작업이 있어도 전체 queued/running이 남아 있으면 polling을 계속한다.
모든 작업이 종료하면 polling을 멈춘다. OpenAPI와 생성 타입을 갱신했다.

## 검증

096과 동일한 .venv 직접 명령과 npm 명령을 실행했다.

| 검사 | 결과 |
| --- | --- |
| `.venv/bin/ruff format --check backend` | 104개 파일 통과 |
| `.venv/bin/ruff check backend` | 통과 |
| `.venv/bin/mypy` | 103개 파일 통과 |
| `.venv/bin/python -m app.openapi --check` | 통과 |
| `.venv/bin/pytest backend/tests/unit backend/tests/integration -q` | 583개 통과 |
| frontend format/lint/typecheck/생성 API 타입 | 모두 통과 |
| `npm --prefix frontend test` | 36개 통과 |
| `make compose-smoke` | 기본 브라우저 3, 재시작 보존 1, 회수 probe, UI 재시도 1 통과 |
| `git diff --check` | 통과 |

51개 녹음에서 최근 목록 밖의 queued, 미래 backoff, running, FAILED와 검토 플래그를
전체 집계함을 확인했다. 필터 적용 시에도 운영 집계가 같고 빈 DB 시각은 null이다.
프런트엔드 회귀는 빈 목록에서도 활성 집계로 polling을 계속하고 종료 뒤 멈추며 단위와
로컬 시간 표시가 맞는지 검사한다. 기존 Starlette/httpx 경고는 남아 있다.
실제 공급자 전용 브라우저 4개는 fake 환경이므로 제외한다.

이 PR 자체는 GPU runtime에 영향을 주지 않아 별도의 실제 NVIDIA/GPU 검증이 불필요하다.
선행 R9-01·02는 실제 STT·화자 실행 경로이므로 GPU 검증 미완료이며 096 서버 인계 절차를 따른다.
R9는 IN PROGRESS를 유지한다. R9-04 이후, 간헐적 SUMMARY_INVALID_OUTPUT 개선,
R6 모델 접근 승인·평가 표본은 후속 작업이다. PR을 게시하되 병합하지 않는다.
