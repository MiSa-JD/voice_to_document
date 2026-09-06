# 요약 오류 진단과 장문 회귀 검증

## 구현

- 외부 `SUMMARY_INVALID_OUTPUT` 코드를 유지하고 구조화 로그 `failure_reason`에
  `response_format`, `refusal`, `incomplete`, `empty_output`, `json_decode`, `schema`,
  `evidence`, `request_rejected`를 구분한다. 허용 목록 밖 사유는 `unspecified`로 제한한다.
- 전체 요약과 chunk 사실 추출의 교정 요청은 기존처럼 최대 한 번이다.
- 요약 전용 예외 경계에서 입력 오류는 `SUMMARY_INVALID_INPUT`, 예상 밖 오류는
  `SUMMARY_PIPELINE_ERROR`로 안전하게 처리한다. `INVALID_FAKE_RESULT` 오분류를 방지한다.
- transcript, 응답 원문, 키, 비공개 경로와 예외 원문을 진단 로그에 넣지 않는다.
  worker 경유 테스트에서 로그와 저장 오류 메시지의 민감 문자열 미포함을 확인했다.
- `python -m app.summary_eval --long`은 공개 합성 회의 한 건만 평가한다.
  기본 5개 범주 평가와 기존 120,000자 chunk 기준은 유지한다.

## 실제 장문 API 평가 (2026-09-07 KST)

- 공개 합성 회의 90개 segment, 45분 타임라인, 본문 32,701자.
- OpenAI `gpt-5.4-nano-2026-03-17`, 요청 timeout 300초, context 기준 120,000자.
- 기존 `.venv`와 임시 데이터 루트에서 평가 진입점 `run(settings, long=True)` 실행.
- **첫 평가 1/1 통과, 13.53초.** 앞·중간·끝 필수 사실과 각각의 segment 근거 보존,
  범주 template, 알려진 근거만 사용, fingerprint 검사 모두 통과.
- 성공 결과를 고르기 위한 반복 실행은 하지 않았다. 원문 입력·응답·키를 출력하지 않았다.
- 합성 표본 한 건의 성공이며 모든 운영 장문의 300초 내 완료를 보장하지 않는다.
  운영 최종 실패는 기존 수동 요약 재요청으로 복구하며 DB를 일괄 변경하지 않는다.

## 최종 로컬 검사

- `.venv`의 기존 도구로 Makefile의 `uv run` 뒤 명령을 직접 실행했다.
  추가 도구 설치나 프로젝트 의존성 변경은 하지 않았다.
- backend `ruff format --check`, `ruff check`, `mypy`, `app.openapi --check`: 통과.
- unit 411개, integration 50개: **461개 통과**.
- frontend format, lint, typecheck, API types 검사 및 `make test-frontend`: **33개 통과**.
- `git diff --check`: 통과.
- Compose 환경을 전체 출력하지 않고 api/worker의 timeout `300`만 확인했다.
- `make compose-smoke`: 통과. 일반 브라우저 검사 3개와 worker 재시작 후 검사 1개 통과.
  별도 실제 분류·요약 E2E 4개는 일반 smoke의 기본 조건에 따라 제외됐다.
  실제 장문 요약 API는 위의 별도 평가로 검증했다.
- 기존 Starlette TestClient의 httpx 사용 deprecation 경고 1건은 테스트 실패가 아니다.
- 요약은 CPU의 호스팅 API 경로이며 GPU 실행·dependency·device·runtime을 변경하지 않는다.
  jobs의 추가 실패 갱신도 summarize에만 적용하므로 실제 NVIDIA/GPU 검증은 불필요하다.

## PR 인계

- `fix/summary-long-recording-retries` → `main` 독립 hotfix PR. 선행·후속 stack 없음.
- 기존 차단 기록과 timeout, 재시도 상태, 오류 진단의 세 구현 커밋을 보존한다.
- 로컬 구현·검증 완료. 게시 후 GitHub Actions를 확인하며 병합은 수행하지 않는다.
- R8 **BLOCKED**, R9 **NOT STARTED** 유지. R8 게이트 해제는 검증과 병합 이후다.
- HTTP API, DB schema, 새 공급자·큐·background API, R6/R9 작업은 범위 밖이다.
