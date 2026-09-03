# R8-02 OpenAI 실제 요약 어댑터

## 작업 관계

- base: `feature/r8-01-summary-schema`
- 선행: R8-01 → 현재 R8-02
- 후속: `feature/r8-03-summary-jobs`

## 구현 결과

- `SummaryAdapter.summarize(transcript, category)` 계약으로 fake와 OpenAI 실제 요약 구현을
  분류 어댑터와 독립적으로 조립했다.
- 기존 분류 경로와 같은 Python 표준 라이브러리 방식으로 Responses API를 호출하며 고정 model,
  `temperature=0`, `reasoning.effort=none`, `store=false`와 범주별 strict JSON Schema를 사용한다.
- system instruction은 transcript를 지시가 아닌 자료로 취급하고, 제공된 근거 밖의 담당자·기한·
  결정 생성을 금지한다.
- 응답은 JSON, 범주별 Pydantic model, transcript 근거 순서로 검증하며 출력 오류는 한 번만 교정한
  뒤 영구 실패한다. refusal, incomplete, 빈 출력도 저장 가능한 결과로 반환하지 않는다.
- timeout, 연결 오류, HTTP 408/429/5xx는 기존 job backoff용 재시도 오류로, 나머지 공급자·출력
  오류는 영구 오류로 구분한다.
- `SUMMARY_CONTEXT_MAX_CHARS=120000`을 설정과 Compose에 추가했다. 초과 입력은 기존 segment
  slicer로 모든 chunk의 근거 사실을 추출하고 전부 최종 범주 요약 요청에 전달한다.
- fingerprint에는 provider, model, temperature, prompt/schema/template version과 digest, context
  전략 및 한도만 남기고 API key, transcript, 공급자 원문, base URL은 제외했다.

## 검증

- 정상 strict 요청, 1회 교정, 근거 위조 거부, refusal/incomplete/빈 출력, timeout/HTTP/연결 오류,
  비밀 비노출, 모든 chunk 보존을 unit test로 검증했다.
- backend format/lint/typecheck: 통과
- backend unit + integration: 404건 통과
- frontend format/lint/typecheck 및 API type drift: 통과
- frontend unit: 25건 통과
- OpenAPI snapshot: 통과
- Compose smoke 및 브라우저 E2E: 3건 통과, 실제 분류 E2E 1건은 전용 명령 대상이라 skip
- worker 재시작 보존 E2E: 1건 통과
- `git diff --check`: 통과

## 비범위

- 분류 완료 시 자동 job 등록과 수동 요청 API
- summary JSON/Markdown 묶음 게시 및 reconciliation
- 최종 상태 UI, 수정 후 stale 정책, 실제 OpenAI 요약 평가

## 개인정보·GPU 판정

오류와 fingerprint에 transcript, credential, 공급자 원문 응답, 전체 endpoint를 남기지 않는다.
이 변경은 OpenAI 호스팅 API를 사용하는 CPU document 경로이며 CUDA/NVIDIA dependency, GPU
runtime, device 선택, WhisperX·pyannote 실행 경로를 변경하지 않아 실제 GPU 검증이 필요하지 않다.
