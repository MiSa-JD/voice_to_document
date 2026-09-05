# R8-01 범주별 요약 스키마

## 작업 관계

- base: `main`
- 현재: `feature/r8-01-summary-schema`
- 후속: `feature/r8-02-summary-adapter`

## 구현 결과

- `lecture`, `meeting`, `daily_conversation`, `game_list`, `other` discriminator를 갖는 범주별
  `CategorySummary` 계약을 추가했다.
- 모든 요약 사실에 하나 이상의 segment 근거를 요구하고 segment ID, 원본 시각, 선택 인용문을
  transcript와 교차 검증한다.
- 회의 할 일은 task, nullable 담당자·기한, 근거를 분리하며 값이 없을 때 Markdown과 UI에서
  `확인되지 않음`으로 표시한다.
- 알려진 범주와 템플릿의 대응을 고정하고 사용자 정의 범주는 `other` 구조로 처리하면서 실제
  표시 범주를 artifact 렌더링에 보존한다.
- 범주별 Markdown renderer, fake fixture, 상세 화면의 다섯 구조 호환 표시, OpenAPI 생성 타입을
  함께 갱신했다.
- 빈 문자열, 빈 근거, 알 수 없는 필드, 위조된 segment·시각·인용문을 거부한다.

## 검증

- backend format/lint/typecheck: 통과
- backend unit + integration: 392건 통과
- frontend format/lint/typecheck: 통과
- frontend unit: 25건 통과
- OpenAPI snapshot 및 frontend API type drift: 통과
- Compose smoke 및 브라우저 E2E: 3건 통과, 실제 분류 E2E 1건은 전용 명령 대상이라 skip
- worker 재시작 보존 E2E: 1건 통과
- `git diff --check`: 통과

## 비범위

- OpenAI 실제 요약 호출과 긴 transcript 처리
- 자동·수동 요약 job 등록 및 요청 API
- 두 summary artifact의 묶음 게시와 재시작 복구
- 최종 상태 UI, stale 재생성, 실제 모델 평가

## 개인정보·GPU 판정

합성 fixture만 사용했고 transcript, 실제 source path, credential을 문서나 로그에 추가하지 않았다.
이 변경은 순수 document schema와 CPU 렌더링 경로이며 CUDA/NVIDIA dependency, GPU runtime,
device 선택, WhisperX·pyannote 실행 경로를 변경하지 않아 실제 NVIDIA/GPU 검증이 필요하지 않다.
