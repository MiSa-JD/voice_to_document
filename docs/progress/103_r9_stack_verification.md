# R9-01~03 최종 스택 검증

작성일: 2026-09-10. 브랜치: `feature/r9-03-operations-visibility`.
선행 순서: main → R9-01 ([#56](https://github.com/MiSa-JD/voice_to_document/pull/56)) →
R9-02 ([#57](https://github.com/MiSa-JD/voice_to_document/pull/57)) → R9-03.

R9-01의 입력 identity·실패 후속 작업 보존 보강(73c7ebd)을 R9-02에 rebase했다.
R9-02의 명시적 STT 재입력 보강을 포함한 c5922f9 위로 R9-03 고유 변경을 다시 rebase했다.
원격 R9-02는 --force-with-lease로 갱신했다. 충돌 없이 각 단계의 전체 검사를 다시 수행했다.

| 전체 브랜치 | backend unit/integration | frontend unit | 일반 검사 | 격리 Compose |
| --- | --- | --- | --- | --- |
| R9-01 | 566 | 33 | 통과 | 기본 브라우저·재시작 보존·SIGKILL probe 통과 |
| R9-02 | 583 | 35 | 통과 | 위 검사와 실패→재시도 UI 통과 |
| R9-03 | 589 | 36 | 통과 | 위 검사와 최종 통합 통과 |

일반 검사는 .venv/bin/ruff format --check backend, .venv/bin/ruff check backend,
.venv/bin/mypy, .venv/bin/python -m app.openapi --check, npm --prefix frontend의
format:check/lint/typecheck/api:types:check, git diff --check다.
backend는 .venv/bin/pytest backend/tests/unit backend/tests/integration -q,
frontend는 npm --prefix frontend test를 실행했다. R9-03 format 104개, mypy 103개 파일 통과.
Compose는 make compose-smoke로 운영과 다른 임시 project·DB·출력을 사용했다.
실제 공급자 전용 브라우저 4개는 fake 환경에서 제외하며 재시도 시나리오는 기본 보존 검사 뒤
별도 실행한다. 기존 Starlette/httpx deprecation 경고는 남아 있다.

GitHub Actions에서 R9-01 최종 73c7ebd와 R9-02 최종 c5922f9의 quality-and-tests,
compose-smoke 통과를 확인했다. R9-03 게시 후 최종 head의 CI 결과와 세 PR의 base/head·
선행/후속 링크를 PR 본문에 갱신한다. PR은 병합하지 않는다.

완료 범위는 R9-01~03 구현·작업별 커밋·진행 기록·일반 검증·스택 PR 게시다.
R9-01·02 실제 NVIDIA/GPU 서버 검증 결과를 사용자에게 인계받았다.
중단 복구, 재시도 시 실패 이력 보존, 기존 재전사는 사용자 확인 기준으로 완료했다.
확인 근거와 범위는 [104 서버 GPU 검증 결과](104_r9_server_gpu_verification.md)에 기록했다.
전사 결과 저장 직후의 정확한 checkpoint 중단·결과 재사용은 별도 실제 GPU 미검증 항목으로 남긴다.
R9-03 자체는 로그·집계·화면 변경으로 GPU runtime에 영향을 주지 않아 별도 실제 GPU 검증이 불필요하다.

R8은 운영 성공과 간헐적 SUMMARY_INVALID_OUTPUT 제한을 함께 수용한 DONE 상태다.
요약 모델·프롬프트·분할·검증 완화·자동 재시도 확대는 수행하지 않았다.
R6 모델 접근 승인·평가 표본 blocker, R9-04 이후 백업·보안·전체 접근성·종합 E2E·운영 문서
완성은 후속 작업이며 R9 전체는 IN PROGRESS를 유지한다.
