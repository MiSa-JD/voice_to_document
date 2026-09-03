# R8-07 실제 요약 평가와 M6 검증

## 작업 관계

- base: `feature/r8-06-summary-stale`
- 선행: R8-06 → 현재 R8-07
- 후속: R9

## 평가 계약

- provider/model: OpenAI Responses API / `gpt-5.4-nano-2026-03-17`
- 요청: temperature `0`, reasoning effort `none`, `store=false`, strict JSON Schema
- 자료: 실제 사람의 발화·경로·식별자가 없는 합성 한국어 transcript 5종
- 통과 기준: 범주 template, 필수 사실의 제한된 의미 표기, 필수·허용 근거 segment, 미정 할 일의
  `assignee=null`·`due_date=null`, Markdown `확인되지 않음`, fingerprint 전체 통과

## 구현 결과

- `backend/tests/fixtures/summary_eval.json`에 강의, 일상 대화, 회의, 게임 목록, 기타 평가 case를
  추가했다. 문장 완전 일치 대신 핵심 용어의 제한된 동의 표기와 근거 segment 보존을 검사한다.
- `make summary-eval`은 실제 응답을 범주 schema와 transcript 근거로 먼저 검증한 뒤 공개 가능한
  검사 결과만 출력한다. 공급자 오류도 원문 없이 해당 case의 `provider_output=false`로 기록하고
  나머지 평가를 계속한다.
- 초기 실제 평가에서 미정 회의 할 일의 구조 보존이 불안정한 점을 발견해 summary prompt를 v2로
  올리고, 명시된 할 일의 누락 금지와 미정 담당자·기한의 JSON `null` 규칙을 강화했다.
- `make summary-e2e`는 자동 회의와 수동 일상 대화를 별도 임시 stack으로 실행한다. 브라우저의
  실패 안내·재시도, 화자 수정 후 stale와 단일 재생성, worker 재시작 뒤 중복 방지, 최신 revision의
  API·JSON·Markdown·UI 일치를 확인하고 종료 시 임시 데이터와 container를 정리한다.
- `AUTO_SUMMARY_CATEGORIES`의 빈 값을 유효한 전체 수동 정책으로 지원해, 실제 분류 결과를 수동
  `일상 대화`로 수정한 뒤 요청 전에는 요약이 없다는 시나리오를 결정적으로 검증한다.
- README에 실제 요약의 개인정보 외부 전송, `store=false`, API 비용, 명령과 출력 제한을 추가했다.

## 실제 평가 결과

- 평가 일시: 2026-09-03 KST
- 실제 OpenAI 요약 평가: 5/5 통과
- 모든 case에서 template, 필수 사실, 필수·허용 근거, 미정 action item null/Markdown 표시,
  fingerprint 검사가 통과했다.
- fingerprint
  - model: `gpt-5.4-nano-2026-03-17`
  - temperature: `0`
  - prompt version: `openai-grounded-summary-v2`
  - prompt SHA-256: `d7bb0a91924c4141b0bf4ce7d03186d9e824e89343fe8ef54d53d501c0df86c8`
  - schema SHA-256: `c78b58700da017bd1f11b6443bb7e7859f5296f6f1e71a8bb714932355da320d`
  - template version: `1`

## 파이프라인과 회귀 검증

- summary evaluation fixture/공개 출력 제한/mock Responses API unit test: 2건 통과
- 실제 `make summary-eval`: 5/5 통과
- 실제 자동 summary E2E: 회의 자동 1회, stale 재생성, API·JSON·Markdown·UI 일치 통과
- 실제 worker 재시작 E2E: 중복 summary job·artifact 없음 통과
- 실제 수동 summary E2E: 일상 대화 요청 전 0회, 실패 안내, 재시도 후 1회 생성 통과
- backend format/lint/typecheck 및 OpenAPI drift: 통과
- backend unit + integration: 428건 통과
- frontend format/lint/typecheck 및 API type drift: 통과
- frontend unit: 33건 통과
- 기본 Compose smoke 및 브라우저 회귀: 통과
- `git diff --check`: 통과
- R8 종료 게이트 M6 전체 통과, R8 상태 `DONE`

## 비범위

- R6 화자 threshold/margin 보정
- inline transcript 편집기
- 다중 LLM 공급자와 background Responses API
- summary 검색·공유 기능

## 개인정보·GPU 판정

평가 및 E2E 입력은 공개 가능한 합성 fixture만 사용했다. transcript, API key, 공급자 원문 응답,
실제 source path는 평가 stdout·진행 문서·fixture에 기록하지 않는다. 이 변경은 OpenAI 호스팅 API를
쓰는 CPU document 경로이며 CUDA/NVIDIA dependency, GPU container/runtime, device 선택,
WhisperX·pyannote 실행 경로를 변경하지 않아 실제 NVIDIA/GPU 검증과 운영 서버 이동이 필요하지 않다.
