# R4-03 — WhisperX 실제 전사 어댑터

- 기록 번호: 033
- 상태: 완료
- 관련 로드맵: R4-03
- 작업 브랜치: `feature/r4-03-whisperx-transcription`
- 완료 시각: 2026-08-26T03:37:23Z

## 작업한 내용

- fake adapter와 분리된 `WhisperXAdapter`를 추가하고 정규화된 WAV 경로만 입력받도록 했다.
- 고정된 WhisperX 3.8.6의 공식 `load_model` → `load_audio` →
  `model.transcribe(batch_size=...)` 호출 흐름을 사용한다.
- model, device, compute type, language, batch size, model cache root를 명시적 설정 계약으로
  정의했다. 기본값은 `large-v3`, `cuda`, `float16`, language 자동 감지, batch size `4`다.
- 모델은 adapter instance에서 지연 로드하고 이후 전사 호출에서 재사용한다.
- raw WhisperX 응답은 외부로 반환하지 않고 언어, 정렬 전 segment의 시작/종료/text와 모델
  fingerprint로 정규화한다.
- fingerprint에는 WhisperX 버전, model, device, compute type, batch size, language 설정만
  포함한다. 토큰, transcript, 입력 경로, model cache 경로는 포함하지 않는다.
- OOM, 모델 로드 실패, 전사 실패, 잘못된 모델 응답을 독립적인 구조화 오류 코드로 분류한다.
- `WHISPER_BATCH_SIZE`를 Settings, `.env.example`, Compose, README와 개발 환경 결정 문서에
  동기화했다. 빈 `WHISPER_LANGUAGE`는 `None`으로 정규화한다.
- 실제 speech mode에서는 `MODEL_CACHE_ROOT`가 절대 경로이며 존재하고 쓰기 가능하고 결과 root와
  겹치지 않는지 시작 시 검증한다.
- GPU 전용 `make transcription-smoke` 진입점을 추가했다. smoke JSON에는 runtime, fingerprint,
  언어, segment 수, cache byte, 처리 시간, 최대 관찰 GPU 메모리만 포함한다.

## 실제 GPU 검증 결과

2026-08-26에 NVIDIA GPU 컨테이너에서 합성 `complete.m4a` fixture를 R4-02 API로 표준화한 뒤
실제 전사를 두 번 실행했다.

- GPU: NVIDIA GeForce RTX 3060 12GB, 1개
- NVIDIA driver: 535.309.01
- Torch: 2.8.0+cu128
- Torch CUDA runtime: 12.8
- WhisperX: 3.8.6
- pyannote.audio: 4.0.7
- model: `large-v3`
- device / compute type / batch size: `cuda` / `float16` / `4`
- language 설정: 자동 감지 (`None`)
- 최초 실행: cache 0 byte에서 6,181,916,415 byte, 76.081초
- cache 재사용 실행: 시작 cache 6,181,858,775 byte, 종료 cache 6,181,895,695 byte,
  15.135초
- 최대 관찰 GPU 메모리: 3,354 MiB (`nvidia-smi` 250ms polling)
- 결과: 두 실행 모두 `status=complete`, 감지 언어 `en`, segment 0개

fixture는 합성 tone이며 pyannote VAD가 활성 음성을 찾지 못했다. 이 결과와 짧은 음원의 자동 감지
언어는 품질 자료로 사용하지 않는다. 실행 로그와 최종 JSON에는 `HF_TOKEN`, transcript 전문,
원본 경로가 없음을 확인했다.

## 자동 검증 결과

- Ruff format: 45개 파일 통과
- Ruff lint: 통과
- mypy strict: 44개 source 파일 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit: 112개 통과
- backend integration: 7개 통과
- React Testing Library: 8개 통과
- Prettier, ESLint, TypeScript strict: 통과
- transcription adapter/config/smoke 전용 테스트: 34개 통과
- 기본 fake Compose api/worker/web health: 통과
- Playwright headless Chromium readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- GPU 실제 transcription smoke: 최초 다운로드 실행과 cache 재사용 실행 통과
- `git diff --check`: 통과

## 알려진 조건과 비범위

- 전체 단위 테스트의 최초 실행에서 기존 SQLite 동시 초기화 테스트가 일시적인 WAL lock으로
  1회 실패했고, 최종 전체 실행은 112개 모두 통과했다. R4-03 변경 파일과 해당 DB 경로는
  겹치지 않는다.
- FastAPI TestClient의 향후 httpx2 전환 경고 1건은 기존과 동일하며 현재 테스트 실패는 없다.
- 실제 worker pipeline 연결은 alignment, diarization, 최종 정규화가 구현되는 R4-04~R4-06까지
  보류한다.
- OOM 등 adapter 오류의 자동 재시도 정책은 R4-07 범위다.
- 실제 녹음의 정확도와 최적 batch size 판정은 R4-08 범위다.

## 참고

- [WhisperX 공식 Python 사용 예시](https://github.com/m-bain/whisperX)
- [WhisperX v3.8.6 release](https://github.com/m-bain/whisperX/releases/tag/v3.8.6)
