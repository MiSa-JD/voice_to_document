# R8-03 자동·수동 요약 작업 등록

## 작업 관계

- base: `feature/r8-02-summary-adapter`
- 선행: R8-02 → 현재 R8-03
- 후속: `feature/r8-04-summary-artifacts`

## 구현 결과

- 분류 완료 시 적용 범주가 `AUTO_SUMMARY_CATEGORIES`이면 `CLASSIFYING → SUMMARIZING` 전이와
  `summarize` job 등록을 한 transaction에서 수행한다. 비자동 범주는 job 없이 `COMPLETED`로
  끝난다.
- `POST /api/recordings/{recording_id}/summary`와 expected revision 계약을 추가했다. 신규 요청은
  202, 같은 revision·category·template fingerprint의 활성/성공 요청은 200과 `created=false`를
  반환한다. 실패 job 뒤 요청은 새 job을 만든다.
- 녹음 없음, revision 충돌, 분류 전 상태, classify/render 진행 상태에 안정적인 404/409/422 오류
  코드를 제공한다.
- 수동으로 실제 생성된 요청만 `summary_requested` audit event로 남긴다.
- job fingerprint에 어댑터 공개 fingerprint, 실제 category와 template을 포함한다.
- worker는 시작 시 input revision, category 기반 fingerprint를 다시 확인해 stale job이면 이전
  입력으로 artifact를 덮어쓰지 않고 종료한다.
- 자동 요약 artifact를 Compose smoke와 기존 브라우저 재시작 검증의 정상 결과에 포함했다.

## 검증

- 자동/수동 정책, 신규·중복·성공·실패 후 재요청, 오류 계약, audit 단일 기록, stale job 무저장을
  integration test로 검증했다.
- backend format/lint/typecheck: 통과
- backend unit + integration: 409건 통과
- frontend format/lint/typecheck: 통과
- frontend unit: 25건 통과
- OpenAPI snapshot 및 frontend API type drift: 통과
- Compose smoke 및 브라우저 E2E: 3건 통과, 실제 분류 E2E 1건은 전용 명령 대상이라 skip
- worker 재시작 보존 E2E: 1건 통과
- `git diff --check`: 통과

## 비범위

- JSON/Markdown의 묶음 게시, 중간 실패 복구, 이전 범주 경로 정리
- 요약 상태/요청 UI와 stale 상태 표현
- 실제 OpenAI 요약 평가와 M6 게이트

## 개인정보·GPU 판정

audit에는 recording ID 관계, revision, category만 남기며 transcript와 credential을 기록하지 않는다.
이 변경은 CPU document job/API 경로이며 CUDA/NVIDIA dependency, GPU runtime, device 선택,
WhisperX·pyannote 실행 경로를 변경하지 않아 실제 NVIDIA/GPU 검증이 필요하지 않다.
