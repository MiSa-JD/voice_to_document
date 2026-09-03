# R8-06 수정 후 요약 stale 처리

## 작업 관계

- base: `feature/r8-05-summary-ui`
- 선행: R8-05 → 현재 R8-06
- 후속: `feature/r8-07-summary-evaluation`

## 구현 결과

- 녹음 전체 화자 배정, 개별 segment 화자 배정, 화자 이름 변경, 범주 변경이 revision을
  증가시키면 이전 요약을 즉시 `stale`로 표시하고 현재 요약 응답에서는 숨긴다.
- transcript render가 끝난 뒤 이전 revision에 요약이 있었거나 새 범주가 자동 요약 대상이면 현재
  revision의 요약 job을 하나만 등록한다. 활성·성공 fingerprint 멱등성을 그대로 사용해 빠르게
  연속 수정되더라도 같은 revision의 중복 job을 만들지 않는다.
- STT 재수행 뒤 분류에서도 과거 요약 존재 여부를 확인한다. 따라서 수동 범주의 과거 요약도 최신
  transcript로 다시 생성하며, 한 번도 요약하지 않은 수동 범주는 계속 요청 전 상태를 유지한다.
- fake summary adapter가 다섯 범주와 사용자 정의 범주의 `other` template을 결정적으로 생성하도록
  보완해 모든 수정 경로를 실제 범주 schema로 검증할 수 있게 했다.
- 범주 변경 중에는 이전 범주 artifact를 보존하되 API에서 stale로 숨기며, 새 revision의 JSON과
  Markdown 저장이 모두 성공한 뒤 기존 안전 정리 절차가 이전 범주 파일을 제거한다.

## 검증

- 화자 이름·녹음 화자·segment 화자·범주·STT 재수행 stale 및 단일 재생성 integration test:
  14건 통과
- backend format/lint/typecheck: 통과
- backend unit + integration: 425건 통과
- frontend format/lint/typecheck: 통과
- frontend unit: 33건 통과
- OpenAPI snapshot 및 frontend API type drift: 통과
- Compose smoke 및 브라우저 E2E: 3건 통과, 실제 분류 E2E 1건은 전용 명령 대상이라 skip
- worker 재시작 보존 E2E: 1건 통과
- `git diff --check`: 통과

## 비범위

- 별도의 inline transcript 텍스트 편집 API
- 실제 OpenAI 요약 품질 평가와 전용 Compose E2E
- R6 화자 threshold/margin 보정

## 개인정보·GPU 판정

테스트에는 합성 fixture만 사용했고 재전사 힌트, transcript 원문, 실제 source path, credential을
로그나 진행 문서에 기록하지 않았다. 이 변경은 CPU document/revision 경로이며 CUDA/NVIDIA
dependency, GPU container/runtime, device 선택, WhisperX·pyannote 실행 경로를 변경하지 않아 실제
NVIDIA/GPU 검증이 필요하지 않다.
