# R4 M2 — 실제 전사 마일스톤 검증

- 기록 번호: 041
- 상태: 완료
- 관련 로드맵: R4 종료 게이트 M2
- 작업 브랜치: `chore/r4-m2-verification`
- 완료 시각: 2026-08-27T02:18:28Z

## 게이트 판정

| 종료 조건 | 판정 | 증거 |
|---|---|---|
| 실제 m4a에서 시간 정보가 있는 transcript 생성 | 통과 | 비공개 세 표본을 실제 worker 전체 경로로 처리했고 181개 시간 segment를 생성했다. |
| 여러 화자를 `SPEAKER_XX`로 분리 | 통과 | 다중 화자 역할에서 `SPEAKER_00`, `SPEAKER_01` 두 화자와 144개 segment를 생성했다. |
| 모든 segment의 시간·범위 불변식 | 통과 | model evaluator가 정렬 순서, 양수 길이, 0 이상 시작과 오디오 길이 이하 종료를 검사했다. |
| OOM과 token 권한의 서로 다른 조치 안내 | 통과 | batch size 8의 실제 `MODEL_OOM`을 관찰했고 R4-07 정책·UI 테스트에서 `MODEL_ACCESS_DENIED`와 다른 조치를 고정했다. |
| R3 fake E2E 회귀 | 통과 | 기본 Compose health, Playwright pipeline 2개와 worker 재시작 보존 1개가 통과했다. |
| 일반 CI와 분리된 재현 가능한 실제 평가 | 통과 | `model-eval` Compose profile과 `make model-eval`로만 실행하며 기본 Compose/CI는 fake runtime을 유지한다. |

세부 장비 fingerprint, 역할별 길이·segment 수, 처리 시간과 batch size 선택 근거는
[R4-08 기록](040_r4_08_fixed_audio_evaluation.md)에 남겼다. 실제 녹음, transcript, 경로와 token은
Git이나 공개 평가 JSON에 포함하지 않았다.

## 최종 자동 검증

- 비공개 실제 m4a `make model-eval`: 통과, batch size `4` 선택, `8`은 `MODEL_OOM`
- backend unit/integration: 218개 통과
- frontend Vitest: 9개 통과
- Ruff format/lint, mypy strict: 통과
- OpenAPI snapshot, 생성 TypeScript 타입, Prettier, ESLint, TypeScript strict: 통과
- 기본 fake Compose api/worker/web health: 통과
- Playwright readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- GPU Compose profile 병합, `git diff --check`: 통과

M2 브랜치는 직전 검증 완료된 R4-08 커밋에서 문서만 변경한다. 따라서 같은 코드 상태에서 수행한
R4-08 실제 모델 평가와 전체 회귀 실행을 M2 최종 증거로 사용하며 불필요한 비공개 음원 재처리는
반복하지 않았다.

## 알려진 품질 관찰과 다음 단계

- 단일 화자 역할이 두 임시 화자로 과분할됐다. R4 완료 기준인 시간 불변식과 다중 화자 구간 생성은
  만족하지만 정확한 화자 수는 보장하지 않는다.
- R5에서 사용자가 임시 화자를 듣고 병합·수정할 수 있는 수동 검토 흐름을 구현하고, R10에서 고정
  표본으로 화자 수·배정 품질을 다시 평가한다.
- R4가 `DONE`이 되어 R5의 M2 선행조건이 충족됐다.
