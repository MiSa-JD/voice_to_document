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
```

`make model-eval`은 R4 이후 Linux NVIDIA GPU에서만 사용합니다. 로컬 fake 개발 흐름은 GPU, `HF_TOKEN`, LLM API 키를 요구하지 않습니다.

## 비밀값과 개인정보

실제 `.env`, Hugging Face 토큰, LLM API 키, 실제 사람의 녹음은 Git에 커밋하지 않습니다. 외부 LLM을 사용하면 transcript가 외부 서비스로 전송될 수 있으며, 공급자와 모델은 R7 전에 확정합니다.

자세한 환경 변수와 Compose 실행 방법은 R1 구현과 함께 이 문서에 추가합니다.

## Compose 실행

기본 개발 구성은 fake 모드이며 브라우저만 `127.0.0.1:8000`에 공개합니다.

```sh
cp .env.example .env
make runtime-dirs
docker compose up --build -d --wait
docker compose down
```

`.env`의 `DATA_ROOT`, `APP_BIND_HOST`, `APP_PORT`로 호스트 경로와 공개 주소를 바꿀 수 있습니다. 컨테이너 내부의 입력·transcript·speaker·summary·app 경로도 `.env`에서 관리하지만, 서로 겹치지 않는 절대 경로여야 합니다.
