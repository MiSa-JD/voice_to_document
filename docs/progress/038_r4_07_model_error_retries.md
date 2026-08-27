# R4-07 — 모델 오류와 재시도 분류

- 기록 번호: 038
- 상태: 완료
- 관련 로드맵: R4-07
- 작업 브랜치: `feature/r4-07-model-error-retries`
- 완료 시각: 2026-08-26T23:08:18Z

## 작업한 내용

- 실제 speech 오류 코드를 자동 재시도 가능한 실패와 사용자 조치가 필요한 영구 실패로 매핑하는
  중앙 정책을 추가했다. 알 수 없는 코드는 안전하게 영구 실패로 처리한다.
- 모델 다운로드의 네트워크·timeout·429·5xx 오류, 전사·정렬·화자 분리의 일시 실행 오류,
  FFmpeg timeout, 입력·artifact I/O 오류는 기존 job queue의 최대 3회 지수 backoff를 사용한다.
- GPU OOM, 모델 접근 거부, 일반 모델/runtime load 실패, FFmpeg 부재, 디스크 부족, 손상 입력,
  미지원 언어와 유효하지 않은 모델 결과는 무의미한 자동 재시도 없이 실패시킨다.
- WhisperX 전사, alignment, pyannote adapter가 모델 접근 거부와 일시적 다운로드 실패를 일반
  load 실패와 별도 코드로 반환하도록 보강했다.
- 재시도 중에도 recording과 job에 같은 정규화 오류 코드와 안전한 사용자 조치 문구를 저장하고,
  다음 시도에서는 `FAILED`에서 `TRANSCRIBING`으로 정상 복귀하게 했다.
- 녹음 상세 처리 이력에 오류 코드, 사용자 조치, 자동 재시도 대기, 사용자 조치 필요, 재시도 종료
  상태를 표시했다. 수동 재시도 동작은 R9-02 범위로 유지했다.
- 원본 예외 메시지, token, 전체 파일 경로와 transcript는 DB, API, 로그와 UI에 전달하지 않는다.

## 오류 정책

- `MODEL_OOM`, `MODEL_ACCESS_DENIED`: 즉시 종료하고 각각 batch size와 `HF_TOKEN` 조치를 안내한다.
- `MODEL_DOWNLOAD_FAILED`: 네트워크와 cache 권한을 안내하며 최대 3회 자동 재시도한다.
- `TRANSCRIPTION_FAILED`, `ALIGNMENT_FAILED`, `DIARIZATION_FAILED`: 일시 실행 실패로 재시도한다.
- `FFMPEG_TIMEOUT`, `INPUT_IO_ERROR`, `ARTIFACT_IO_ERROR`: 일시 I/O 실패로 재시도한다.
- 손상·잘못된 입력, 잘못된 응답, 미지원 언어, 실행 파일·디스크·runtime 설정 문제는 영구
  실패로 처리한다.

## 자동 검증 결과

- Ruff format/lint: 57개 backend 파일 통과
- mypy strict: 56개 source 파일 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit: 192개 통과
- backend integration: 7개 통과
- React Testing Library: 9개 통과
- Prettier, ESLint, TypeScript strict: 통과
- 기본 fake Compose api/worker/web health: 통과
- Playwright headless Chromium readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- `git diff --check`: 통과

FastAPI TestClient 테스트는 샌드박스 밖에서 실행해 모두 통과했다. 기존 httpx2 전환 경고 1건은
테스트 실패나 현재 API runtime 오류가 아니다. Makefile의 Python 명령은 샌드박스 밖 `uv` cache가
읽기 전용이라 실행되지 않아 저장소 `./.venv`의 고정 실행 파일로 동일 검증을 직접 수행했다.

## 알려진 조건과 비범위

- 오류의 사용자가 누르는 수동 재시도 API와 버튼, 운영자용 종합 실패 화면은 R9-02 범위다.
- exception chain 분류는 원본 메시지를 외부에 노출하지 않고 알려진 HTTP·network 표식을 사용한다.
  고정 dependency의 오류 형태가 바뀌면 adapter 회귀 테스트와 함께 표식을 갱신한다.
- 실제 네트워크 단절과 OOM을 GPU worker에서 강제로 발생시키는 평가는 일반 자동 테스트에 넣지
  않았다. 정책과 상태 전이는 주입 adapter로 재현했다.

## 다음 작업

- R4-08 전용 브랜치에서 비공개 단일 화자, 다중 화자, 무음 포함 표본을 처리하는 격리된
  `make model-eval`을 구현하고 Linux RTX 3060에서 M2 실제 모델 게이트를 검증한다.
