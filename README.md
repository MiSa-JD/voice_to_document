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
```

`make model-smoke`는 Linux x86_64 NVIDIA 장비에서 CUDA와 고정된 Torch 2.8,
WhisperX 3.8.6, pyannote import를 확인합니다. 이 명령은 실제 모델을 다운로드하거나
녹음을 전사하지 않습니다. `make model-eval`은 R4-08에서 실제 평가가 연결된 뒤 사용합니다.

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

## AI 모드

speech와 document 공급자는 독립적으로 선택합니다. R4 실제 음성 모델과 기존 fake document를
함께 사용할 때는 다음처럼 설정합니다.

```dotenv
SPEECH_MODE=real
DOCUMENT_MODE=fake
HF_TOKEN=your-private-token
```

`SPEECH_MODE=real`은 `HF_TOKEN`만 요구합니다. LLM 관련 변수는 `DOCUMENT_MODE=real`에서만
필수입니다. 기존 `AI_MODE`는 직접 실행 호환용으로 읽지만 새 설정에서는 사용하지 않습니다.

GPU runtime만 검증하려면 NVIDIA driver와 NVIDIA Container Toolkit을 준비한 뒤 실행합니다.

```sh
make model-smoke
```

성공 출력은 GPU/driver/CUDA와 패키지 버전만 포함하며 토큰이나 전체 환경 변수는 출력하지
않습니다.
