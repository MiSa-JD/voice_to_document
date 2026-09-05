# R8-04 요약 artifact 안전 저장과 경로 정리

## 작업 관계

- base: `feature/r8-03-summary-jobs`
- 선행: R8-03 → 현재 R8-04
- 후속: `feature/r8-05-summary-ui`

## 구현 결과

- category path 입력에서 `/`, `\\`, `..`, NUL과 모든 제어 문자를 거부하고 기존 설정 시작 시
  slug 충돌 차단을 유지했다.
- summary JSON과 Markdown을 revision 전용 경로에 각각 임시 파일로 쓰고 file/directory fsync 후
  게시한다. 두 파일이 준비된 다음 두 artifact row를 한 transaction으로 등록한다.
- JSON 또는 Markdown 게시 중 실패하거나 DB 등록 전 실패하면 현재 revision의 일부 결과가 API의
  성공 artifact로 노출되지 않는다.
- worker 시작 reconciliation이 현재 revision의 JSON을 범주 schema와 transcript 근거로 검증하고,
  Markdown 누락 또는 DB 부분 등록을 범주별 renderer로 복구한다. 검증 불가능한 JSON은 정상
  결과로 승격하지 않는다.
- 범주가 바뀌면 새 범주 파일 두 개와 DB 등록이 성공한 뒤 이전 범주의 summary row와 파일을
  정리한다. 새 저장 실패 시 이전 성공 파일과 row를 보존한다.
- Compose smoke는 root의 flat transcript와 revision별 summary 파일을 각각 검증한다.

## 검증

- 경로/제어 문자, JSON·Markdown 단계별 실패, DB 전 실패, pair 등록, 새 범주 성공 전·후 정리,
  재시작 복구와 invalid JSON 비승격을 unit/integration test로 검증했다.
- backend format/lint/typecheck: 통과
- backend unit + integration: 418건 통과
- frontend format/lint/typecheck: 통과
- frontend unit: 25건 통과
- OpenAPI snapshot 및 frontend API type drift: 통과
- Compose smoke 및 브라우저 E2E: 3건 통과, 실제 분류 E2E 1건은 전용 명령 대상이라 skip
- worker 재시작 보존 E2E: 1건 통과
- `git diff --check`: 통과

## 비범위

- 상세 API의 summary 파생 상태와 사용자 요청 UI
- 모든 revision 변경 경로의 stale 정책 정리
- 실제 OpenAI 요약 평가와 M6 게이트

## 개인정보·GPU 판정

reconciliation 오류는 안전한 코드와 recording 관계만 기록하며 transcript 내용과 실제 경로를
로그에 남기지 않는다. 이 변경은 CPU 파일/DB document 경로이며 CUDA/NVIDIA dependency, GPU
runtime, device 선택, WhisperX·pyannote 실행 경로를 변경하지 않아 실제 GPU 검증이 필요하지 않다.
