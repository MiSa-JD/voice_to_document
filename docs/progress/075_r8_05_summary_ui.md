# R8-05 요약 상태와 요청 UI

## 작업 관계

- base: `feature/r8-04-summary-artifacts`
- 선행: R8-04 → 현재 R8-05
- 후속: `feature/r8-06-summary-stale`

## 구현 결과

- 상세 API에 `summary_status`, `summary_policy`, 현재 revision의 `summary_job`,
  `summary_can_request`를 추가했다. `summary`는 현재 revision의 JSON과 Markdown이 모두 등록된
  검증 결과만 반환한다.
- 상태는 `not_requested`, `queued`, `running`, `succeeded`, `stale`, `failed`로 파생하며 이전
  revision 결과를 현재 요약으로 반환하지 않는다.
- 상세 화면은 자동 대기, 수동 요청 가능, 생성 중, 최신 완료, stale, 실패 재시도를 구분한다.
- 요청 중 버튼을 비활성화하고 성공 응답 뒤 최신 상세가 반영될 때까지 재요청을 막는다. 서버의
  fingerprint 멱등성과 함께 빠른 중복 클릭도 job 하나로 제한한다.
- 409 revision 충돌은 최신 상세를 다시 불러오고, 422와 네트워크 오류는 다음 행동을 안내한다.
- 기존 recording 상태 polling에 summary queued/running 상태를 추가하고 완료·실패 시 중단한다.
- 요약 상태 영역에 `aria-live`, 명시적 button, 기존 공통 focus 스타일을 적용해 키보드만으로
  요청과 재시도가 가능하다.

## 검증

- backend 상태/policy/job/requestability와 stale 숨김 integration test: 통과
- frontend 여섯 상태, 중복 클릭, 성공, revision 충돌 unit test: 통과
- backend format/lint/typecheck: 통과
- backend unit + integration: 419건 통과
- frontend format/lint/typecheck: 통과
- frontend unit: 33건 통과
- OpenAPI snapshot 및 frontend API type drift: 통과
- Compose smoke 및 브라우저 E2E: 3건 통과, 실제 분류 E2E 1건은 전용 명령 대상이라 skip
- worker 재시작 보존 E2E: 1건 통과
- `git diff --check`: 통과

## 비범위

- 모든 revision 변경 경로의 공통 stale 재등록 정책
- 실제 OpenAI 요약 평가 및 실제 요약 전용 Compose E2E

## 개인정보·GPU 판정

상태 API와 UI에 transcript 원문, source path, credential을 새로 노출하지 않는다. 이 변경은 CPU
document API/UI 경로이며 CUDA/NVIDIA dependency, GPU runtime, device 선택, WhisperX·pyannote
실행 경로를 변경하지 않아 실제 NVIDIA/GPU 검증이 필요하지 않다.
