# R8 장문 요약 운영 hotfix 차단 기록

## 우선순위 결정

- **R9 작업을 시작하지 않는다.** 먼저 이 문서의 요약 운영 문제를 독립 hotfix PR로 해결한다.
- hotfix 브랜치는 최신 `main`에서 `fix/summary-long-recording-retries`로 분기하고 PR base는
  `main`으로 한다.
- 이 hotfix가 검증되고 병합되기 전까지 R8은 `BLOCKED`, R9은 `NOT STARTED`로 유지한다.
- 기존 R8 구현과 M6 검증 결과는 유효한 개발 증거로 보존하되, 운영에서 흔한 40~50분 녹음의
  실패가 확인됐으므로 R8 완료 게이트를 다시 연다.

## 운영에서 확인된 문제

- 실제 document 모드에서 장문 요약 요청이 고정 60초 read timeout에 걸려
  `SUMMARY_TIMEOUT`으로 세 번 실패했다.
- 재시도 가능한 첫 실패부터 recording을 `FAILED`로 바꿔 다음 시도에서
  `FAILED → FAILED` 전이 오류가 발생했다.
- 이 상태에서는 다음 공급자 요청이 성공하더라도 artifact 저장 후 `FAILED → COMPLETED` 전이가
  거부될 수 있다. 재시도가 성공 결과를 정상 완료로 확정할 수 없는 상태 처리 결함이다.
- 별도 실제 요청에서는 `SUMMARY_INVALID_OUTPUT`이 발생했지만, 현재 로그만으로는 refusal,
  incomplete, JSON decode, schema 또는 evidence 검증 중 어느 단계가 실패했는지 구분할 수 없다.
- 이전 `INVALID_FAKE_RESULT` 사례도 실제 mode 설정과 예외 분류 경계를 함께 확인해야 한다.
  실제 transcript, 공급자 원문 응답, API key와 내부 식별자는 문서나 일반 로그에 남기지 않는다.

## hotfix 범위

1. 요약 공급자 timeout을 `SUMMARY_REQUEST_TIMEOUT_SECONDS` 설정으로 분리하고 API와 worker에
   같은 값을 전달한다. 기본값은 실제 40~50분 녹음을 고려해 정하고 `.env.example`과 Compose에
   기록한다.
2. 재시도 가능한 실패에서는 recording을 `SUMMARIZING`으로 유지하고 job만 재예약한다. 최종
   시도까지 실패했을 때만 recording을 한 번 `FAILED`로 전환한다.
3. 재시도 요청이 성공하면 artifact 등록과 `SUMMARIZING → COMPLETED`가 정상적으로 끝나게 한다.
4. `SUMMARY_INVALID_OUTPUT`은 민감한 원문 없이 refusal, incomplete, empty output, invalid JSON,
   schema, evidence처럼 조치 가능한 안전한 세부 원인을 구조화 로그에 남긴다.
5. 40~50분 분량에서 단일 요청이 계속 불안정한 것이 확인될 때만 기존 chunk 전략의 기준을
   조정한다. 새 큐, 새 공급자 또는 background Responses API는 이 hotfix에 추가하지 않는다.

## 완료 조건과 검증

- 첫 번째와 두 번째 timeout 뒤 recording은 `SUMMARIZING`이고 job은 재시도 대기 상태다.
- 세 번째 timeout 뒤 job과 recording은 중복 상태 전이 오류 없이 각각 최종 실패 상태가 된다.
- timeout 뒤 다음 시도가 성공하는 테스트에서 최신 revision의 JSON/Markdown artifact가 하나만
  등록되고 recording은 `COMPLETED`가 된다.
- 실제 mode에서 발생한 잘못된 출력은 민감정보 없이 안전한 실패 단계로 구분된다.
- 합성 장문 transcript로 timeout 설정과 재시도 성공/최종 실패 회귀 테스트를 통과한다.
- backend format, lint, typecheck, unit, integration, API schema와 `git diff --check`를 통과한다.
- Compose에서 설정 전달을 확인하고, 공개 가능한 합성 입력으로 실제 OpenAI 장문 요약을 한 번
  검증한다. 비용이 발생하며 transcript와 공급자 원문은 stdout에 출력하지 않는다.
- 이 변경은 OpenAI 호스팅 API를 사용하는 CPU document 경로에 한정한다. CUDA/NVIDIA dependency,
  GPU container/runtime, device 선택과 WhisperX·pyannote 경로를 변경하지 않으므로 실제 GPU 검증은
  필요하지 않다.

## 비범위

- R9의 stale job 회수, 백업·복원, 접근성 마감과 전체 릴리스 후보 작업
- R6 화자 자동 식별 보정
- 새 외부 dependency, DB migration, 다중 LLM 공급자
- 비공개 실제 녹음이나 transcript를 fixture 또는 진행 문서에 추가하는 작업

