# R4-05 — pyannote 화자 분리

- 기록 번호: 036
- 상태: 완료
- 관련 로드맵: R4-05
- 작업 브랜치: `feature/r4-05-pyannote-diarization`
- 완료 시각: 2026-08-26T06:52:30Z

## 작업한 내용

- WhisperX 3.8.6의 `DiarizationPipeline`을 통해
  `pyannote/speaker-diarization-community-1`을 호출하는 `WhisperXDiarizationAdapter`를
  추가했다.
- 모델은 지연 로드하고 adapter 인스턴스 안에서 재사용한다. `HF_TOKEN`, CUDA device와 기존
  `MODEL_CACHE_ROOT`를 사용하며 원본 경로와 토큰은 공개 결과와 오류 메시지에 포함하지 않는다.
- pyannote의 원시 label을 시간순 최초 등장 기준으로 `SPEAKER_00` 형식의 녹음별 안정적인 임시
  화자 ID로 변환한다. turn 시간은 유한값과 양수 길이를 검증하고 오디오 범위로 제한한다.
- aligned text segment와 화자 turn의 교집합 시간을 화자별로 합산해 주 화자를 할당한다. 합계가
  같으면 먼저 등장한 turn과 speaker ID 순서로 결정해 결과를 재현 가능하게 했다.
- 서로 다른 화자 turn이 실제로 동시에 겹친 segment는 `overlap` 상태와 관련 화자 ID 목록으로,
  직접 겹치는 turn이 없는 segment는 `unassigned`와 `local_speaker_id=None`으로 명시한다. 시간상
  순차적으로만 만나는 여러 화자는 overlap으로 잘못 표시하지 않는다.
- OOM, 모델/token 접근 거부, 모델 로드 실패, diarization 실행 실패, 잘못된 응답을 구조화된 오류
  코드로 구분했다.
- GPU 전용 `make diarization-smoke`와 Compose profile을 추가했다. 이 명령은 FFmpeg 표준화,
  WhisperX 전사, alignment, pyannote diarization을 순서대로 실제 실행한다.

## 실제 GPU 검증 결과

2026-08-26에 `make diarization-smoke`를 Linux NVIDIA GPU 환경에서 실행했다.

- GPU: NVIDIA GeForce RTX 3060, 1개
- NVIDIA driver: 535.309.01
- Torch / CUDA runtime: 2.8.0+cu128 / 12.8
- WhisperX / pyannote.audio: 3.8.6 / 4.0.7
- diarization model / device: `pyannote/speaker-diarization-community-1` / `cuda`
- cache: 6,559,531,440 byte → 6,625,312,683 byte
- 처리 시간: 23.410초
- 최대 관찰 GPU 메모리: 3,706 MiB
- 결과: `status=complete`, turn 0개, speaker 0개, text segment 0개

합성 tone fixture는 WhisperX VAD가 활성 음성을 찾지 못해 diarization 결과도 비어 있었다. 빈
결과에서도 community-1 모델을 실제로 cache에서 로드하고 pyannote pipeline을 호출했으며, 빈
turn과 빈 assignment를 정상 결과로 처리했다. 화자 수와 분리 품질은 R4-08의 실제 음성 평가
자료로 판단한다.

## 자동 검증 결과

- Ruff format: 53개 파일 통과
- Ruff lint: 통과
- mypy strict: 52개 source 파일 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit/integration: 175개 통과
- diarization adapter/smoke 전용 테스트: 31개 통과
- React Testing Library: 8개 통과
- Prettier, ESLint, TypeScript strict: 통과
- 기본 fake Compose의 api/worker/web health: 통과
- Playwright headless Chromium readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- 실제 GPU diarization smoke: 통과
- `git diff --check`: 통과

FastAPI TestClient 기반 테스트는 샌드박스 밖에서 실행해 모두 통과했다. 향후 httpx2 전환에 관한
기존 deprecation warning 1건은 테스트 실패나 현재 API runtime 오류가 아니다.

## 알려진 조건과 비범위

- 합성 tone smoke는 모델 접근과 호출 계약을 검증하지만 실제 다중 화자 분리 품질은 검증하지
  않는다.
- overlap과 unassigned는 R4-05 내부 결과에서 손실 없이 표현한다. 기존 R3 `Segment` schema,
  DB 저장과 `transcript.json` 반영은 R4-06 범위다.
- 모델 접근 오류의 worker 재시도 여부와 사용자 조치 안내 연결은 R4-07 범위다.

## 다음 작업

- R4-06 전용 브랜치에서 전사·alignment·diarization 결과를 R3 schema로 정규화해 DB와
  transcript artifact에 저장한다.
