# R5-02 — 대표 클립 선택과 생성

- 기록 번호: 053
- 상태: 완료
- 관련 로드맵: R5-02
- 작업 브랜치: `feature/r5-02-speaker-clips`
- 기준 브랜치: `main`
- 완료일: 2026-08-29

## 작업한 내용

- SQLite schema를 v6으로 올리고 `recording_speakers`에 `pending`, `ready`, `insufficient`,
  `failed` 대표 클립 상태와 안전한 오류 코드를 추가했다. 기존 화자는 `pending`으로 backfill된다.
- `speaker_clips` 원장을 추가해 녹음 내 화자, 원본 segment, 동적 artifact, 녹음 revision,
  0부터 시작하는 표시 순서, 실제 클립 시간 범위, 무음 비율을 연결했다.
- 일반 `assigned`이고 2초 이상인 segment만 후보로 삼는다. 시간순으로 후보를 고정하고 중심 간격이
  10초 이상인 구간을 화자별 최대 3개 선택하므로 입력 순서나 재시도 횟수와 무관하게 결과가 같다.
- 각 구간 중앙에서 최대 8초를 잘라 FFmpeg로 mono 16 kHz PCM WAV를 만든다. 20 ms 창 RMS로
  계산한 무음 비율이 40%를 넘는 후보는 등록하지 않고 다음 후보를 검사한다.
- 채택된 클립은 `SPEAKER_ROOT/<recording-id>/<local-speaker-id>/<index>.wav`에 기존의
  fsync 및 atomic replace 경로로 저장한다. artifact kind에 화자와 순서를 포함하고 동일 revision을
  upsert해 재시작과 재시도에도 artifact identity 및 원장 행 수가 증가하지 않는다.
- 유효한 클립이 2개 이상이면 `ready`, 0~1개이면 `insufficient`로 기록한다. FFmpeg 누락,
  timeout, 디스크 부족, 잘못된 WAV와 변환 실패는 원본 경로나 FFmpeg stderr를 저장하지 않는
  안전한 코드와 `failed` 상태로 남긴다.
- fake 및 real transcript가 segment와 transcript JSON을 보존한 직후 클립 생성을 호출한다.
  클립 부가 처리의 예외는 상위 transcript·분류 흐름을 실패시키지 않도록 격리했다.

## 자동 검증 결과

- Ruff format/lint와 `git diff --check`: 통과
- mypy strict: 73개 source 파일 통과
- Prettier, ESLint, TypeScript strict: 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit: 272개 통과
  - v5→v6 backfill과 migration 재실행 멱등성
  - 후보 결정성, 최소 길이, overlap/unassigned 제외, 중심 간격, 최대 길이
  - 고정 창 무음 비율과 40% 초과 후보 제외, 부족/준비/실패 상태
  - FFmpeg 실패 안전 코드, 실제 FFmpeg fixture의 mono 16 kHz PCM 출력
  - atomic artifact 쓰기 재사용과 같은 revision 재시도 identity/행 수 멱등성
- backend integration: 15개 통과
- frontend unit: 9개 통과

## 비범위와 다음 작업

- 원본 녹음 artifact 등록과 Range 재생 endpoint는 R5-03에서 구현한다.
- person 생성·수정과 화자/segment 수동 연결은 R5-04에서 구현한다.
- 이번 변경은 GPU 모델을 다시 실행하지 않으므로 GPU 검증은 수행하지 않고 FFmpeg fixture를
  직접 변환해 검증했다.
- 비공개 transcript 본문, 원본 절대 경로와 credential은 테스트 출력과 이 문서에 기록하지 않았다.
