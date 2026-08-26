# R4-02 — FFmpeg 오디오 표준화

- 기록 번호: 032
- 상태: 완료
- 관련 로드맵: R4-02
- 작업 브랜치: `feature/r4-02-ffmpeg-normalization`
- 완료 시각: 2026-08-26T03:18:48Z

## 작업한 내용

- 원본을 수정하지 않고 고유 임시 작업 디렉터리에 mono, PCM signed 16-bit, 16 kHz WAV를
  생성하는 `normalized_audio` context manager를 추가했다.
- FFmpeg를 shell 없이 인자 배열로 실행하고 첫 번째 audio stream만 선택하며 video와 metadata는
  결과에서 제외했다.
- context 종료와 변환 실패, timeout, 호출자 예외를 포함한 모든 경로에서 정규화 WAV와 작업
  디렉터리를 제거한다.
- FFmpeg 실행 파일 없음, timeout, 사용할 수 없는 audio stream, 디스크 공간 부족, 일반 변환
  실패를 구조화된 오류 코드로 구분한다.
- 오류 메시지에는 입력 전체 경로나 FFmpeg stderr를 포함하지 않는다.

## 실제 FFmpeg 검증

- 기존 `complete.m4a` fixture를 공백과 한글이 포함된 경로로 복사해 실제 FFmpeg로 변환했다.
- ffprobe 결과가 `pcm_s16le`, sample format `s16`, sample rate `16000`, channel `1`인지 확인했다.
- 변환 context 안팎에서 원본 byte가 유지되는지, context 종료 후 작업 디렉터리가 삭제되는지
  확인했다.

## 자동 검증 결과

- Ruff format: 41개 파일 통과
- Ruff lint: 통과
- mypy strict: 40개 source 파일 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit: 87개 통과 (`test_media.py` 14개 포함)
- backend integration: 7개 통과
- React Testing Library: 8개 통과
- Prettier, ESLint, TypeScript strict: 통과
- 기본 fake Compose api/worker/web health: 통과
- Playwright headless Chromium readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- `git diff --check`: 통과

## 알려진 조건과 비범위

- FastAPI TestClient의 향후 httpx2 전환 경고 1건은 기존과 동일하며 현재 테스트 실패는 없다.
- 정규화 WAV는 후속 처리 중에만 존재하며 artifact나 결과 root에 저장하지 않는다.
- 실제 WhisperX 호출과 정규화 WAV 소비는 R4-03에서 구현한다.
- alignment, diarization, 최종 transcript 저장은 R4-04~R4-06 범위다.

## 다음 작업

- 이 완료 커밋에서 `feature/r4-03-whisperx-transcription` 브랜치를 만든다.
- R4-03에서 WhisperX 어댑터와 GPU 전용 실제 전사 smoke를 구현한다.
