# R4-04 — WhisperX 정렬(Alignment) 어댑터

- 기록 번호: 034
- 상태: 완료
- 관련 로드맵: R4-04
- 작업 브랜치: `feature/r4-04-whisperx-alignment`
- 완료 시각: 2026-08-26T06:26:43Z

## 작업한 내용

- WhisperX 3.8.6의 `load_align_model`과 `align` 호출을 캡슐화한
  `WhisperXAlignmentAdapter`를 추가했다.
- 감지 또는 고정된 언어 코드를 정규화하고 언어별 alignment 모델을 지연 로드해 adapter
  인스턴스 안에서 재사용한다.
- 정렬된 segment와 단어의 시작·종료·score를 애플리케이션 전용 불변 dataclass로 변환하고,
  원시 WhisperX 응답은 외부 계약으로 노출하지 않는다.
- 단어 timestamp가 누락되거나 한쪽만 존재해도 전체 정렬을 실패시키지 않고 해당 단어의 시간을
  `None`으로 표시한다. 정렬 결과에서 segment가 누락되면 R4-03 전사 segment의 시간과 텍스트를
  보존한다.
- segment와 단어 시간은 유한값인지 검사하고 `0..audio_duration` 범위로 제한한다. 잘못된 역방향
  segment 시간은 전사 결과로 복구한다.
- OOM, 지원되지 않는 언어, 모델/runtime 로드 실패, 정렬 실행 실패, 잘못된 응답을 구조화된 오류
  코드로 구분하고 오류 메시지에 입력 경로나 모델 내부 오류를 노출하지 않는다.
- fingerprint에는 WhisperX 버전, device, 보간 방식, 언어만 포함한다.
- GPU 전용 `make alignment-smoke`와 Compose profile을 추가해 FFmpeg 표준화, 실제 전사,
  alignment를 한 번에 재현할 수 있게 했다. smoke 출력에는 transcript나 토큰, 원본 경로를
  포함하지 않는다.

## 실제 GPU 검증 결과

2026-08-26에 `make alignment-smoke`를 Linux NVIDIA GPU 환경에서 실행했다.

- GPU: NVIDIA GeForce RTX 3060, 1개
- NVIDIA driver: 535.309.01
- Torch / CUDA runtime: 2.8.0+cu128 / 12.8
- WhisperX / pyannote.audio: 3.8.6 / 4.0.7
- 전사 model / device / compute type / batch size: `large-v3` / `cuda` / `float16` / `4`
- alignment device / interpolate method / 언어: `cuda` / `nearest` / `en`
- cache: 6,181,866,967 byte → 6,559,568,360 byte
- 처리 시간: 22.631초
- 최대 관찰 GPU 메모리: 3,578 MiB
- 결과: `status=complete`, segment 0개, word 0개

fixture는 합성 tone이며 WhisperX VAD가 활성 음성을 찾지 못했다. 자동 감지 언어와 segment/word
개수는 alignment 품질 자료로 사용하지 않으며 실제 음성 평가는 R4-08에서 수행한다. 빈
transcript에서도 영어 wav2vec2 alignment 모델을 실제로 다운로드·로드하고 `whisperx.align`을
호출해 alignment runtime 경계가 동작하는 것을 확인했다.

## 자동 검증 결과

- Ruff format: 49개 파일 통과
- Ruff lint: 통과
- mypy strict: 48개 source 파일 통과
- Prettier, ESLint, TypeScript strict: 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit/integration: 144개 통과
- alignment adapter/smoke 전용 테스트: 25개 통과
- React Testing Library: 8개 통과
- 기본 fake Compose의 api/worker/web health: 통과
- Playwright headless Chromium readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- 실제 GPU alignment smoke: 통과
- `git diff --check`: 통과

FastAPI TestClient 기반 8개 테스트는 실행 샌드박스 안에서 포털 스레드가 멈추는 환경 제약을
확인한 뒤 비샌드박스 환경에서 통과시켰다. 향후 httpx2 전환에 관한 기존 deprecation warning
1건은 테스트 실패나 현재 API runtime 오류가 아니다.

## 알려진 조건과 비범위

- 합성 tone smoke는 모델 다운로드와 호출 계약을 검증하지만 실제 발화의 단어 정렬 품질은
  검증하지 않는다.
- pyannote diarization과 임시 화자 할당은 R4-05 범위다.
- 실제 worker pipeline, DB segment와 `transcript.json` 저장은 R4-06 범위다.
- alignment 모델의 미지원 언어 정책과 재시도 여부를 worker 오류 정책에 연결하는 작업은
  R4-07 범위다.

## 다음 작업

- R4-05 전용 브랜치에서 pyannote diarization과 `SPEAKER_XX` 임시 화자 할당을 구현한다.
