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
녹음을 전사하지 않습니다. `make model-eval`은 아래의 비공개 고정 음성 표본으로 전체 실제 speech
worker 경로와 batch size 후보를 평가합니다.

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
`MODEL_CACHE_ROOT`에 영속화됩니다. 한국어 alignment가 처음 사용하는 NLTK tokenizer 자료는
보안 검사를 만족하는 전용 `0700` 권한의 `NLTK_CACHE_ROOT`에 저장되며 컨테이너 사용자 홈에는
쓰지 않습니다.

## 비밀값과 개인정보

실제 `.env`, Hugging Face 토큰, LLM API 키, 실제 사람의 녹음은 Git에 커밋하지 않습니다. 외부 LLM을 사용하면 transcript가 외부 서비스로 전송될 수 있으며, 공급자와 모델은 R7 전에 확정합니다.

자세한 환경 변수와 Compose 실행 방법은 R1 구현과 함께 이 문서에 추가합니다.

## Compose 실행

기본 서버 구성은 `SPEECH_MODE=fake`인 개발용 stack이며 브라우저 서비스는 모든 인터페이스의
`38000` 포트에 공개합니다. 같은 장비에서는 `http://127.0.0.1:38000`으로 접속합니다.

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

입력 폴더, 내부 transcript JSON, 사람이 읽는 Markdown을 서로 다른 호스트 위치에 두려면
컨테이너 경로는 그대로 두고 다음 호스트 경로만 설정합니다. `.env`에서 공백이 포함된 경로는
backslash로 escape하지 않고 값 전체를 작은따옴표로 감쌉니다.

```dotenv
RECORDING_INPUT_HOST_DIR=/mnt/syncthing/recordings
TRANSCRIPT_HOST_DIR=/mnt/storage/transcripts
DOCUMENT_HOST_DIR='/mnt/Obsidian/My Vault/3. Resource/vtd'
```

세 변수를 비워 두면 각각 `${DATA_ROOT}/inbox`, `${DATA_ROOT}/transcripts`,
`${DATA_ROOT}/documents`를 사용합니다. 호스트 디렉터리는 Compose 실행 전에 만들고, transcript와
document 디렉터리는 `APP_RUN_UID:APP_RUN_GID`가 쓸 수 있어야 합니다.
`RECORDING_INPUT_DIR=/data/inbox`, `TRANSCRIPT_ROOT=/data/transcripts`,
`DOCUMENT_ROOT=/data/documents`는 컨테이너 내부 경로이므로 일반적으로 변경하지 않습니다.

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

수동 확정한 화자의 대표 클립은 `finalize_speakers` 작업에서 `pyannote/embedding`으로 처리합니다.
모델·revision·device는 `SPEAKER_EMBEDDING_MODEL`, `SPEAKER_EMBEDDING_MODEL_REVISION`,
`SPEAKER_EMBEDDING_DEVICE`로 설정하며, 실제 weight 해시와 전처리 버전을 embedding metadata에
함께 저장합니다. 벡터는 `app.db`의 고정된 `sqlite-vec` 저장소에만 보관되고 서로 다른 model
fingerprint끼리는 비교하지 않습니다. `pyannote/embedding` 모델 사용 조건도 Hugging Face에서
승인되어 있어야 합니다.

인물 profile은 같은 model fingerprint의 현재 활성 sample만 집계합니다. 두 개 이상의 깨끗한
대표 clip이 있을 때 정규화 centroid를 만들고, sample이 하나뿐이거나 화자 연결이 취소된 경우에는
자동 확정 후보로 사용할 수 없는 `insufficient` 상태를 유지합니다. profile centroid는 빠른 후보
검색용이며 원본 sample membership도 보존해 후속 점수 계산에서 재검증할 수 있습니다.

GPU runtime만 검증하려면 NVIDIA driver와 NVIDIA Container Toolkit을 준비한 뒤 실행합니다.

```sh
make model-smoke
make transcription-smoke
make alignment-smoke
make diarization-smoke
```

실제 m4a를 STT→Markdown으로 처리할 때는 `SPEECH_MODE=real`, `DOCUMENT_MODE=fake`,
`HF_TOKEN`을 설정하고 GPU override를 함께 지정합니다. 이 구성은 worker만 speech 의존성이
포함된 이미지, model cache와 GPU를 사용하고 API와 web은 기본 이미지를 유지합니다.

```sh
docker compose -f compose.yaml -f compose.gpu.yaml up --build -d --wait
docker compose -f compose.yaml -f compose.gpu.yaml down
```

실제 worker는 원본 m4a를 임시 mono 16 kHz WAV로 표준화한 뒤 전사, alignment, diarization,
local fake 분류를 순서대로 실행합니다. 동일 revision의 schema v2 JSON은
`${TRANSCRIPT_HOST_DIR:-${DATA_ROOT}/transcripts}/<recording-id>/transcript.json`, Markdown은
`${DOCUMENT_HOST_DIR:-${DATA_ROOT}/documents}/0001_<첫 발화 20자>.md` 형태로 document root에 바로
저장됩니다. 번호와 제목은 최초 렌더 때 고정됩니다. Markdown에는 timestamp와 `SPEAKER_XX`
임시 화자가 표시되며 실제 화자 이름 확정은 R5 범위입니다.

성공 출력은 GPU/driver/CUDA와 패키지 버전만 포함하며 토큰이나 전체 환경 변수는 출력하지
않습니다. 실제 전사 smoke의 합성 tone/무음 결과는 품질이나 최적 batch size를 판단하는 자료로
사용하지 않으며 해당 평가는 아래의 비공개 고정 음성 평가로 분리합니다.

## 실제 음성 평가

다음 세 실제 m4a를 Git에서 제외된 `MODEL_EVAL_ROOT`에 둡니다. 파일명과 transcript는 평가
결과나 로그에 기록하지 않으며, 평가 중 생성된 DB와 artifact는 임시 디렉터리와 함께 제거됩니다.

```text
runtime/model-eval/
├── single-speaker.m4a
├── multi-speaker.m4a
└── silence.m4a
```

`single-speaker.m4a`는 한 명, `multi-speaker.m4a`는 두 명 이상, `silence.m4a`는 발화와 의미 있는
무음 구간을 포함해야 합니다. Linux NVIDIA 장비에서 다음 명령을 실행합니다.

```sh
make model-eval
```

기본 batch size 후보는 `4,8,16`입니다. 모든 표본의 시간·화자 불변식을 만족하고 GPU 메모리의
90% 이하를 사용한 후보 중 가장 빠른 값과 10% 이내인 가장 작은 batch를 선택합니다. 공개 JSON은
장비·모델 fingerprint, 역할별 길이·segment/화자 수, 처리 시간과 GPU 메모리만 포함합니다.

RTX 3060 12GB 평가에서 batch size `4`는 세 표본을 모두 처리하고 최대 7,638 MiB를 사용했으며,
`8`은 OOM으로 종료됐습니다. 따라서 기본값 `4`를 유지합니다. 단일 화자 표본이 두 임시 화자로
과분할된 결과는 숨기지 않고 품질 관찰값으로 기록하며, 이 평가는 문장 완전 일치나 화자 수 정확도
대신 시간 범위·정렬 순서와 다중 화자 구간 생성 여부를 완료 게이트로 사용합니다.
