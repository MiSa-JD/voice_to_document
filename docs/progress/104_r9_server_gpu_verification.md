# R9-01·02 서버 GPU 검증 결과 반영

작성일: 2026-09-10. 기록 브랜치: `docs/r9-server-gpu-verification`.
base: `feature/r9-03-operations-visibility` (78268d1, PR #58).
선행 기록: 096 서버 검증 인계, 101 복구 경계 보조 명령, 102 재전사 보강, 103 스택 검증.
PR 의존 순서: R9-01 [#56](https://github.com/MiSa-JD/voice_to_document/pull/56) →
R9-02 [#57](https://github.com/MiSa-JD/voice_to_document/pull/57) →
R9-03 [#58](https://github.com/MiSa-JD/voice_to_document/pull/58) → 이 검증 기록 PR.
사용자 요청에 따라 검증 기록도 기존 스택 뒤에 별도 커밋·PR로 게시한다.

## 사용자 서버 검증 완료

사용자가 서버에서 실행한 결과를 대화로 인계했다. 아래 완료 판정은 사용자 확인과
제공된 회수 로그에 근거하며, 에이전트가 실제 GPU 테스트를 직접 실행한 결과는 아니다.
이전 진행 기록의 서버 결과 대기 상태를 아래 확인 범위에 대해 갱신한다.

| 확인 항목 | 결과 | 근거 |
| --- | --- | --- |
| 전사 도중 worker 강제 종료 후 재시작·중단 복구 | 완료 — 사용자 확인 | 복구 성공 보고 및 `job_recovered`, `stage=transcribe`, `action=restart` 로그 |
| worker 종료 후 재시도 시 기존 실패 기록 보존 | 완료 — 사용자 확인 | 재시도 시 실패 기록이 남는 동작을 확인했다고 보고 |
| 기존 전용 재전사 기능 | 완료 — 사용자 확인 | 기존 재전사도 정상 작동했다고 보고 |

제공된 로그의 job ID는 `fd1a9dba-c3da-42b8-b549-f086b7738545`, recording ID는
`ce55e6a4-dde8-416e-9313-7ae426514ba3`이다. 회수 시점의 `attempt=1`,
`error_code=null`을 확인했다. 회수 로그 자체는 완료 로그가 아니므로, 중단 복구의
성공 판정은 사용자의 성공 보고와 함께 기록한다. 다음 claim의 attempts 증가와
새 재시도 job ID·최종 성공 로그는 이 대화에 별도로 제공되지 않았다.
기존 전용 재전사 성공과 실패 작업의 수동 재시도는 서로 다른 확인 항목으로 취급한다.

## 남은 검증 범위와 진행 상태

전사 JSON 저장 직후의 정확한 checkpoint에서 강제 종료하고 저장 결과·segment ID를
유지하며 GPU 전사를 재호출하지 않는 시나리오는 실제 GPU에서 별도로 확인하지 않았다.
클립·후속 작업 중복 방지도 이번 서버 보고만으로 추가 통과 판정하지 않는다.
해당 복구 경계의 기존 fake 회귀·Compose 검증 결과는 101·103을 참조한다.
화자 임베딩 경로의 별도 실제 실행 결과는 인계되지 않았으며,
R6 모델 접근 승인·평가 표본 blocker는 유지한다.

사용자와 확인한 판단은 서버에서 확인한 주요 동작을 완료로 기록하고,
남은 실제 GPU 미검증 범위를 명시한 상태로 순차 머지를 판단할 수 있다는 것이다.
PR은 병합하지 않는다. 게시 후 최종 head의 CI와 base/head 관계를 확인하고 PR 본문에 반영한다.
R9-03 자체의 로그·집계·화면 변경에는 별도 GPU 검증이 불필요하다.
R9 전체는 IN PROGRESS이며 R9-04 이후 작업과 간헐적 요약 출력 오류 후속 범위는 유지한다.

## 이번 기록 변경 검증

문서만 변경했다. `git diff --check`와 새 문서에 대한
`git diff --no-index --check /dev/null docs/progress/104_r9_server_gpu_verification.md`를 실행했다.
문서 자체는 GPU 실행 경로를 사용하거나 변경하지 않으므로 추가 실제 GPU 검증은 불필요하다.
스택 게시 절차에 따라 전체 브랜치에서 다음 일반 검사를 다시 실행해 모두 통과했다.

- `.venv/bin/ruff format --check backend`, `.venv/bin/ruff check backend`: 통과.
- `.venv/bin/mypy`, `.venv/bin/python -m app.openapi --check`: 통과.
- `.venv/bin/pytest backend/tests/unit backend/tests/integration -q`: 589개 통과.
- `npm --prefix frontend run format:check`, `lint`, `typecheck`, `api:types:check`: 각각 통과.
- `npm --prefix frontend test`: 36개 통과.

기존 Starlette/httpx deprecation 경고 1개는 유지된다. 문서 변경이므로 로컬 Compose는
반복하지 않으며, 게시 후 최종 head의 `quality-and-tests`와 `compose-smoke`를 확인한다.
비공개 원문·원본 경로·credential은 기록하지 않았다.
