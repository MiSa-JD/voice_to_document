# 개발 환경 조정 — 프로젝트 로컬 Python 패키지

- 기록 번호: 001
- 상태: 완료
- 관련 로드맵: R0-01 보완
- 완료 시각: 2026-08-25T05:09:04Z

## 작업한 내용

- Makefile의 `UV_PROJECT_ENVIRONMENT`를 저장소 루트 `./.venv`의 절대 경로로 고정했다.
- 모든 `uv sync`와 `uv run` 명령이 시스템 Python의 전역 site-packages가 아니라 프로젝트 가상 환경을 사용하도록 했다.
- README에 Python 프로젝트 패키지는 `./.venv`에만 설치한다는 원칙을 추가했다.
- `.venv/`는 Git 추적 대상에서 제외된 상태를 유지했다.

## 검증 결과

- `make -pn`에서 `UV_PROJECT_ENVIRONMENT`가 저장소의 `.venv`를 가리키는 것을 확인했다.
- `make -n install`이 `uv sync --frozen`과 npm lockfile 설치만 실행하는 것을 확인했다.
- 현재 저장소에 `.venv`가 아직 생성되지 않았고 프로젝트 Python 패키지도 설치되지 않았음을 확인했다.
- 앞서 lockfile 생성에 사용한 uv 실행 파일은 `/tmp/voice_to_document_uv`에 있으며 프로젝트 패키지가 아니다.

## 남은 문제와 결정

- 현재 시스템 Python 3.14에는 작업 전부터 FastAPI와 pytest가 설치되어 있지만 이 프로젝트는 해당 전역 패키지를 사용하지 않는다.
- 실제 프로젝트 의존성 설치는 R1 소스 검증 전에 `make install`로 `./.venv`에 수행한다.

## 다음 작업

- R0-02에서 FFmpeg 합성 m4a fixture와 fake 기대 결과를 완성한다.
