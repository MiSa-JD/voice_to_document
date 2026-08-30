# R7-06 OpenAI 실제 분류 경로

## 범위

- OpenAI Responses API의 strict JSON Schema Structured Outputs로 transcript를 실제 분류한다.
- 기존 긴 transcript 전략을 재사용해 전체 분류 또는 모든 segment slice의 주제 추출 후 최종 분류를 수행한다.
- speech의 fake/real과 document의 fake/real 네 조합을 worker에서 독립적으로 조립한다.

## 구현

- 별도 SDK 없이 Python 표준 라이브러리 HTTPS POST로 `{LLM_BASE_URL}/responses`를 호출한다.
- 고정 instruction은 transcript 문장을 지시가 아닌 자료로 취급하며, 동적 category enum과
  `schema_version`, `category`, `confidence`, `reason` 필수 필드를 strict schema로 제한한다.
- refusal, incomplete, 빈 출력, 잘못된 JSON/schema/category는 정상 결과로 저장하지 않는다.
  교정 가능한 출력 오류는 한 번만 다시 요청한 뒤 영구 실패로 처리한다.
- timeout, HTTP 408/429/5xx와 연결 실패는 기존 job backoff를 사용하는 재시도 오류로 변환하고,
  나머지 4xx와 반복된 출력 오류는 영구 오류로 변환한다.
- fingerprint에는 provider, model snapshot, temperature, prompt/schema version과 SHA-256만 기록한다.
  API key, transcript, provider 응답 본문, 전체 base URL은 기록하지 않는다.
- `LLM_PROVIDER`는 `openai_compatible`만 허용한다. 외부 endpoint는 HTTPS만 허용하고,
  HTTP는 `localhost` 및 loopback IP에만 허용하며 userinfo/query/fragment는 거부한다.
- `LLM_API_KEY`는 Compose worker에만 전달한다. API는 `DOCUMENT_MODE=real` 표시를 위해 key 없이
  시작할 수 있다.

## 설정

- provider: `openai_compatible`
- base URL: `https://api.openai.com/v1`
- model: `gpt-5.4-nano-2026-03-17`
- API key: Git 추적 제외 `.env`의 worker 환경에서만 설정

## 검증

- 요청 계약, 정상 응답, fingerprint, refusal/incomplete/빈 출력, JSON/schema/category 오류와 1회
  교정, timeout/HTTP/연결 오류 분류, 비밀값 및 provider 본문 비노출 unit test를 추가했다.
- 긴 transcript의 모든 slice와 부분 주제가 최종 요청에 포함되는지 검증했다.
- fake speech와 mock OpenAI document 분류가 동일 revision JSON/Markdown을 생성하는 integration
  test를 추가했다.
- 네 speech/document 조합, API key 없는 API 설정, worker의 key/provider/URL 검증을 추가했다.
- format/lint/typecheck/OpenAPI drift: 통과
- backend unit: 353건 통과
- backend integration: 26건 통과
- frontend unit: 25건 통과
- Compose smoke 및 브라우저 E2E: 전체 3건과 worker 재시작 1건 통과
- `git diff --check`: 통과

## GPU 판정

이 변경은 CUDA/NVIDIA dependency, GPU container/runtime, device 선택, WhisperX·pyannote 실행
경로를 변경하지 않는다. OpenAI 호스팅 API의 document 분류 경로만 추가하므로 실제 NVIDIA/GPU
검증은 필요하지 않다.
