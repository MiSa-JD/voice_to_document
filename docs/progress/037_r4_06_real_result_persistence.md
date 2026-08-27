# R4-06 — 실제 결과 정규화와 저장

- 기록 번호: 037
- 상태: 완료
- 관련 로드맵: R4-06
- 작업 브랜치: `feature/r4-06-real-result-persistence`
- 완료 시각: 2026-08-26T22:45:16Z

## 작업한 내용

- transcript schema를 v2로 올리고 segment 화자 배정을 `assigned`, `overlap`, `unassigned`로
  명시했다. 미배정 segment는 `local_speaker_id=null`을, 겹침 segment는 관련 임시 화자 ID를
  손실 없이 보존한다.
- SQLite schema v3 migration으로 기존 segment를 `assigned` 상태로 호환 이전하고 새로운 화자
  배정 필드를 저장하게 했다.
- 실제 speech worker가 원본 m4a를 임시 mono 16 kHz WAV로 표준화한 뒤 WhisperX 전사,
  alignment, pyannote diarization을 순서대로 실행하도록 연결했다.
- 실제 결과를 녹음 범위 안의 밀리초 단위로 변환하고 시간순으로 정렬했다. 빈 텍스트와 0 길이
  구간은 제외하고, 유효 segment가 없거나 alignment와 화자 배정이 맞지 않으면 잘못된 모델
  결과로 실패시킨다.
- segment ID는 recording UUID와 원래 segment index로 결정해 같은 결과의 재실행에서 안정적으로
  유지한다.
- 전사, alignment, diarization fingerprint를 `transcript.json`에 저장하고 원시 모델 응답은
  artifact나 DB에 저장하지 않는다.
- 정규화 segment를 DB와 schema v2 `transcript.json`에 저장한 뒤 녹음을 `SPEAKER_REVIEW`로
  전환한다. 원본 녹음과 임시 WAV 정리 규칙은 유지한다.
- 녹음 상세 API, OpenAPI snapshot, 생성 TypeScript 타입과 React 상세 화면에 겹침·미배정 화자
  계약을 반영했다.
- GPU Compose override를 실제 worker에도 적용해 speech 의존성, model cache와 단일 NVIDIA GPU를
  사용하게 했다. 기본 Compose의 fake worker는 계속 GPU 없이 실행된다.

## 자동 검증 결과

- Ruff format/lint: 55개 backend 파일 통과
- mypy strict: 54개 source 파일 통과
- Prettier, ESLint, TypeScript strict: 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit/integration: 188개 통과
  - 일반 샌드박스: TestClient 제외 180개 통과
  - 비샌드박스 TestClient: 8개 통과, 기존 httpx2 전환 경고 1건
- R4-06 real pipeline 전용: 5개 통과
- React Testing Library: 8개 통과
- 기본 fake Compose api/worker/web health: 통과
- Playwright headless Chromium readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- GPU Compose 병합 설정 검증: 통과
- `git diff --check`: 통과

## 실제 모델 검증 범위

- R4-03~R4-05에서 같은 고정 버전과 cache를 사용한 실제 전사, alignment, diarization smoke가 각각
  통과했다.
- R4-06에서는 모델 adapter를 주입한 통합 테스트로 FFmpeg 표준화, 호출 순서, 시간 정규화,
  DB/artifact 저장, 상태 전이와 실패 기록을 검증했다.
- 실제 단일·다중 화자 녹음의 품질과 전체 worker GPU 평가는 R4-08 고정 음성 평가에서 수행한다.

## 알려진 조건과 비범위

- 전체 backend 회귀의 첫 최종 실행에서 기존 SQLite 동시 초기화 테스트가 WAL lock으로 1회
  실패했고, 즉시 재실행한 최종 결과는 TestClient 제외 180개가 모두 통과했다. 같은 일시 실패는
  R4-03 기록에도 있으며 R4-06의 schema migration 검증은 별도로 모두 통과했다.
- 모델 오류 코드는 현재 adapter의 구조화 코드를 보존한다. 오류별 재시도 여부와 사용자 조치 안내
  세분화는 R4-07 범위다.
- 모든 실제 speech segment는 아직 실제 인물과 연결되지 않았으므로 화자 검토 대기 상태가 된다.
  수동 화자 확정과 검토 완료 후 분류 재개는 R5 범위다.
- 실제 document mode는 R7 전까지 worker 시작 시 명시적으로 차단한다.

## 다음 작업

- R4-07 전용 브랜치에서 OOM, 모델 접근·다운로드, 손상 입력과 일시적 I/O 오류의 재시도 및 사용자
  조치 정책을 연결한다.
