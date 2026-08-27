# Voice to Document

Syncthing 입력 폴더의 m4a 녹음을 감지해 transcript, 분류, 요약 문서를 만드는 로컬 우선 시스템입니다. 현재 개발 기준은 외부 모델 없이 반복 가능한 fake 어댑터 수직 흐름입니다.

## 개발 환경

- Python 3.11 + [uv](https://docs.astral.sh/uv/)
- Node.js 24 + npm
- FFmpeg/ffprobe
- Docker 및 Docker Compose

의존성은 `uv.lock`과 `frontend/package-lock.json`으로 고정합니다.
Python 프로젝트 패키지는 저장소 루트의 `./.venv`에만 설치합니다. 시스템 Python이나 전역 site-packages는 사용하지 않습니다.

```sh
make install
```

`make install`은 `uv sync --frozen`을 실행하며 Makefile의 `UV_PROJECT_ENVIRONMENT`가 `./.venv`로 고정되어 있습니다.

## 공통 명령

```sh
make check-format
make lint
make typecheck
make api-schema-check
make test-unit
make test-frontend
make test-integration
make test-e2e
make test
make compose-smoke
make model-smoke
make transcription-smoke
make alignment-smoke
make diarization-smoke
```

`make model-smoke`는 Linux x86_64 NVIDIA 장비에서 CUDA와 고정된 Torch 2.8,
WhisperX 3.8.6, pyannote import를 확인합니다. 이 명령은 실제 모델을 다운로드하거나
녹음을 전사하지 않습니다. `make model-eval`은 R4-08에서 실제 평가가 연결된 뒤 사용합니다.

`make transcription-smoke`는 GPU model image에서 합성 M4A fixture를 mono 16 kHz PCM WAV로
표준화한 뒤 WhisperX `large-v3`를 실제로 로드하고 batch size `4`로 전사합니다. 첫 실행은 모델
다운로드 때문에 오래 걸리며 `MODEL_CACHE_ROOT` cache를 이후 실행에서 재사용합니다. 출력 JSON은
GPU/driver/CUDA, 모델 fingerprint, 감지 언어, segment 수, 처리 시간, cache 사용량과 관찰된 최대
GPU 메모리만 포함하고 transcript 전문, 원본 경로, `HF_TOKEN`은 포함하지 않습니다.

`make alignment-smoke`는 같은 표준화·실제 전사 흐름 뒤에 감지 언어용 WhisperX alignment
모델을 로드해 단어 시간을 보정합니다. 출력 JSON에는 전사·정렬 fingerprint, 언어, segment와
word 개수, 단어 시간이 생성된 segment 수, 처리 시간, cache와 GPU 메모리만 포함합니다.

`make diarization-smoke`는 alignment 뒤에
`pyannote/speaker-diarization-community-1`을 실행하고 녹음 안의 화자를 `SPEAKER_00` 형식으로
정규화합니다. 출력 JSON에는 모델 fingerprint, 화자·turn 수, 배정·겹침·미배정 segment 수,
처리 시간, cache와 GPU 메모리만 포함하며 transcript 전문은 출력하지 않습니다.

기본 `make install`과 Compose는 speech extra를 설치하지 않으므로 GPU, `HF_TOKEN`, LLM API 키를
요구하지 않습니다. 모델 image의 다운로드 cache는 애플리케이션 결과와 분리된
`MODEL_CACHE_ROOT`에 영속화됩니다.

## 비밀값과 개인정보

실제 `.env`, Hugging Face 토큰, LLM API 키, 실제 사람의 녹음은 Git에 커밋하지 않습니다. 외부 LLM을 사용하면 transcript가 외부 서비스로 전송될 수 있으며, 공급자와 모델은 R7 전에 확정합니다.

자세한 환경 변수와 Compose 실행 방법은 R1 구현과 함께 이 문서에 추가합니다.

## Compose 실행

기본 서버 구성은 fake 모드이며 브라우저 서비스는 모든 인터페이스의 `38000` 포트에
공개합니다. 같은 장비에서는 `http://127.0.0.1:38000`으로 접속합니다.

```sh
cp .env.example .env
make runtime-dirs
docker compose up --build -d --wait
docker compose down
```

`.env`의 `DATA_ROOT`, `APP_BIND_HOST`, `APP_PORT`로 호스트 경로와 공개 주소를 바꿀 수 있습니다.
Linux 호스트의 사용자 ID가 기본 `1000:1000`과 다르면 `APP_RUN_UID=$(id -u)`와
`APP_RUN_GID=$(id -g)`에 해당하는 숫자로 바꿔 bind mount 쓰기 권한을 맞춥니다. 컨테이너
내부의 입력·transcript·speaker·summary·app 경로도 `.env`에서 관리하지만, 서로 겹치지 않는
절대 경로여야 합니다.

입력 폴더와 transcript를 서로 다른 호스트 위치에 두려면 컨테이너 경로는 그대로 두고 다음
호스트 경로만 설정합니다.

```dotenv
RECORDING_INPUT_HOST_DIR=/mnt/syncthing/recordings
TRANSCRIPT_HOST_DIR=/mnt/storage/transcripts
```

두 변수를 비워 두면 각각 `${DATA_ROOT}/inbox`, `${DATA_ROOT}/transcripts`를 사용합니다. 호스트
디렉터리는 Compose 실행 전에 만들고, transcript 디렉터리는 `APP_RUN_UID:APP_RUN_GID`가 쓸 수
있어야 합니다. `RECORDING_INPUT_DIR=/data/inbox`와 `TRANSCRIPT_ROOT=/data/transcripts`는
컨테이너 내부 경로이므로 일반적으로 변경하지 않습니다.

## AI 모드

speech와 document 공급자는 독립적으로 선택합니다. R4 실제 음성 모델과 기존 fake document를
함께 사용할 때는 다음처럼 설정합니다.

```dotenv
SPEECH_MODE=real
DOCUMENT_MODE=fake
HF_TOKEN=your-private-token
```

`SPEECH_MODE=real`은 `HF_TOKEN`만 요구합니다. LLM 관련 변수는 `DOCUMENT_MODE=real`에서만
필수입니다. `WHISPER_LANGUAGE`를 비우면 언어를 자동 감지하며 `WHISPER_BATCH_SIZE` 기본값은
RTX 3060 12GB용 보수적 시작값인 `4`입니다. 실제 speech runtime의 `MODEL_CACHE_ROOT`는 결과
디렉터리와 겹치지 않는, 존재하고 쓰기 가능한 절대 경로여야 합니다. 기존 `AI_MODE`는 직접 실행
호환용으로 읽지만 새 설정에서는 사용하지 않습니다.

GPU runtime만 검증하려면 NVIDIA driver와 NVIDIA Container Toolkit을 준비한 뒤 실행합니다.

```sh
make model-smoke
make transcription-smoke
make alignment-smoke
make diarization-smoke
```

실제 speech worker를 실행할 때는 GPU override를 함께 지정합니다. 이 구성은 worker만 speech
의존성이 포함된 이미지와 GPU를 사용하고 API와 web은 기본 이미지를 유지합니다.

```sh
docker compose -f compose.yaml -f compose.gpu.yaml up --build -d --wait
docker compose -f compose.yaml -f compose.gpu.yaml down
```

실제 worker는 원본 m4a를 임시 mono 16 kHz WAV로 표준화한 뒤 전사, alignment, diarization을
순서대로 실행합니다. 정규화된 segment와 모델 fingerprint는 schema v2 `transcript.json`과
SQLite에 저장되고, 미확정·겹침·미배정 화자는 검토 대기 상태로 보존됩니다.

성공 출력은 GPU/driver/CUDA와 패키지 버전만 포함하며 토큰이나 전체 환경 변수는 출력하지
않습니다. 실제 전사 smoke의 합성 tone/무음 결과는 품질이나 최적 batch size를 판단하는 자료로
사용하지 않으며 해당 평가는 R4-08에서 수행합니다.
