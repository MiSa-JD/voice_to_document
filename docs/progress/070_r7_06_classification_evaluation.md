# R7-06 실제 분류 평가와 M5 검증

## 평가 계약

- model snapshot: `gpt-5.4-nano-2026-03-17`
- provider: OpenAI Responses API
- temperature: `0`
- 자료: 실제 사람의 발화·경로·식별자가 없는 합성 한국어 transcript 5종
- 기대 범주: 강의, 일상 대화, 회의, 게임 목록, 기타 각 1건
- 통과 기준: 5/5 기대 범주 일치, schema version 1, 허용 범주, 0~1 confidence,
  비어 있지 않은 reason

## 구현

- `backend/tests/fixtures/classification_eval.json`에 case ID, segment, 기대 범주만 저장한다.
- `make classification-eval`은 CPU 기반 runtime container에서 합성 fixture만 읽고 실제 OpenAI
  Responses API를 호출한다. GPU profile과 NVIDIA runtime을 사용하지 않는다.
- 출력은 case ID, 기대/실제 범주, 성공 여부, model, prompt/schema fingerprint와 aggregate만
  포함한다. transcript, API key, provider 원문 응답은 출력하지 않는다.

## 실제 평가 결과

- fixture 범주 구성, 공개 출력 제한, mock Responses API 5/5 unit test: 통과
- 평가 일시: 2026-09-01 12:49 KST
- 실제 OpenAI 평가: 5/5 통과
  - `lecture-concepts-qa`: 강의 → 강의, confidence 0.93
  - `daily-meal-weekend`: 일상 대화 → 일상 대화, confidence 0.93
  - `meeting-decisions-actions`: 회의 → 회의, confidence 0.97
  - `game-priority-list`: 게임 목록 → 게임 목록, confidence 0.98
  - `other-equipment-check`: 기타 → 기타, confidence 0.86
- 모든 결과: 허용 범주, schema version 1, 0~1 confidence, 비어 있지 않은 reason 충족
- fingerprint
  - model: `gpt-5.4-nano-2026-03-17`
  - temperature: `0`
  - prompt version: `openai-category-classifier-v1`
  - prompt SHA-256: `4889adcbcefd728ad95739cf0dbf5d26e55f817280c8506ca3fd28cf47926f69`
  - schema SHA-256: `d00fdf8bb88d447ac8b697ce7799ccfe978f8be2c1fe9a6548e459a8796d4de0`

## 파이프라인과 회귀 검증

- format/lint/typecheck/OpenAPI drift: 통과
- backend unit 355건, integration 26건, frontend unit 25건: 통과
- 기존 fake Compose smoke와 브라우저 E2E 3건, worker 재시작 E2E 1건: 통과
- API key 누락 시 평가 container가 API를 호출하지 않고 비밀 노출 없는 한 줄 오류로 종료하며
  Compose 자원을 정리함을 확인했다.
- 실제 `make classification-eval`: 5/5 통과
- `make classification-e2e`: 통과
  - fake speech 입력 감지와 transcript 생성
  - 실제 OpenAI 자동 분류 `회의`
  - 브라우저/API 자동 분류 표시
  - 브라우저에서 수동 범주 `강의` 저장
  - revision 2 API, versioned transcript JSON, Markdown, UI 일치
  - 자동 제안 `회의` 보존과 수동 적용 우선 확인
- transcript 본문, API key, provider 원문 응답은 평가 출력·진행 문서에 기록하지 않았다.
- R7 종료 게이트 M5 전체 통과, R7 상태 `DONE`

## 개인정보와 GPU 판정

평가 입력은 저장소에 공개 가능한 합성 문장뿐이며 실제 transcript, 비공개 경로, credential을
출력하거나 문서에 기록하지 않는다. 이 변경은 CUDA/NVIDIA dependency, GPU runtime/device,
WhisperX·pyannote 실행 경로를 변경하지 않으므로 실제 NVIDIA/GPU 검증은 필요하지 않다.
