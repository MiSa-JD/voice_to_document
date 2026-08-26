# R4-01 — GPU worker runtime과 모델 의존성

- 기록 번호: 030
- 상태: 완료
- 관련 로드맵: R4-01
- 작업 브랜치: `feature/r4-01-gpu-runtime`
- 완료 시각: 2026-08-26T02:38:04Z

## 작업한 내용

- 기본 fake runtime과 Linux x86_64 GPU model runtime을 Docker target과 uv `speech` extra로
  분리했다.
- WhisperX 3.8.6, Torch/Torchaudio 2.8.0, Torchvision 0.23.0과 CUDA 12.8 wheel을
  `uv.lock`에 고정했다.
- GPU 예약을 사용하는 `model-smoke` Compose profile과 `make model-smoke` 진입점을 추가했다.
- 모델 cache를 결과물과 분리된 `MODEL_CACHE_ROOT` bind mount에 영속화했다.
- 기존 `AI_MODE`를 호환 입력으로 유지하면서 `SPEECH_MODE`와 `DOCUMENT_MODE`를 분리했다.
  실제 speech는 `HF_TOKEN`만 요구하고 실제 document 모드만 LLM 자격증명을 요구한다.
- model smoke 출력은 GPU, driver, CUDA와 패키지 버전만 포함하며 토큰과 전체 환경 변수를
  출력하지 않게 했다.
- 호스트 bind mount 권한을 `APP_RUN_UID`/`APP_RUN_GID`로 맞추고, Compose smoke가 실제
  `.env`, 실행 중인 Compose project, 사용 중인 포트와 격리되게 했다.
- 디스플레이 없는 서버 운영 기준에 따라 기본 web bind를 `0.0.0.0:38000`으로 변경하고
  신뢰할 수 있는 LAN과 방화벽 안에서만 사용한다는 조건을 문서화했다.
- 작업별 전용 브랜치, progress 문서, 검증 완료 커밋 규칙을 로드맵 운영 규칙에 추가했다.

## 실제 GPU 검증 결과

`make model-smoke`를 실제 Linux NVIDIA 장비에서 실행해 다음을 확인했다.

- 상태: `ready`
- GPU: NVIDIA GeForce RTX 3060, 1개
- NVIDIA driver: 535.309.01
- Torch: 2.8.0+cu128
- Torch CUDA runtime: 12.8
- WhisperX: 3.8.6
- pyannote.audio: 4.0.7

사용자가 사전에 실행한 호스트 `nvidia-smi`와
`docker run --rm --gpus all ubuntu:22.04 nvidia-smi`도 통과한 상태다.

## 자동 검증 결과

- Ruff format: 41개 파일 통과
- Ruff lint: 통과
- mypy strict: 40개 source 파일 통과
- Prettier, ESLint, TypeScript strict: 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit: 77개 통과
- backend integration: 7개 통과
- React Testing Library: 8개 통과
- 기본 fake Compose의 api/worker/web health: 통과
- Playwright headless Chromium readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- GPU model image build와 runtime smoke: 통과
- `git diff --check`: 통과

## 알려진 조건과 비범위

- FastAPI TestClient의 향후 httpx2 전환 경고 1건은 기존과 동일하며 현재 테스트 실패는 없다.
- 이 작업은 모델 패키지와 CUDA runtime import까지만 검증했다. `large-v3`와 pyannote 모델
  다운로드, 실제 전사, alignment, diarization은 R4-03~R4-05에서 수행한다.
- `make model-eval`은 R4-08 전까지 의도적으로 실행 불가 상태를 유지한다.
- `0.0.0.0:38000`에는 애플리케이션 인증이 없으므로 인터넷에 직접 노출하지 않는다.

## 다음 작업

- 새 작업 브랜치에서 R4-02 FFmpeg 표준화를 구현한다.
- 작업 완료 증거는 `docs/progress/031_r4_02_ffmpeg_normalization.md`에 기록한다.
