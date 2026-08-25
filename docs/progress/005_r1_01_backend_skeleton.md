# R1-01 — Python 백엔드 골격

- 기록 번호: 005
- 상태: 완료
- 관련 로드맵: R1-01
- 완료 시각: 2026-08-25T05:13:55Z

## 작업한 내용

- Python 3.11 프로젝트 의존성을 저장소의 `./.venv`에 lockfile 그대로 설치했다.
- Pydantic Settings 기반 `.env`/프로세스 환경 설정 로더를 구현했다.
- 필수 절대 경로의 존재·접근 가능 여부와 위험한 중첩을 검증하도록 했다.
- 허용 범주와 자동 요약 범주의 포함 관계, scan/stable 시간, 포트 범위를 검증하도록 했다.
- fake 모드는 비밀값 없이 실행하고 real 모드는 HF/LLM 변수 이름을 포함해 누락을 거부하도록 했다.
- 서비스와 event를 포함하는 구조화 JSON stdout formatter를 구현했다.
- 비밀값을 public 설정 요약에서 제외하고 Pydantic의 SecretStr로 마스킹했다.

## 검증 결과

- `ruff check`: 통과
- 설정·로그 대상 `mypy --strict`: 통과
- 설정·로그 단위 테스트: 8개 통과
- 실제 프로젝트 패키지가 저장소의 `.venv`에 설치된 것을 확인했다.

## 남은 문제와 결정

- real 모드의 실제 WhisperX/pyannote/LLM 연결은 R4 이후 범위다.
- 경로는 애플리케이션이 임의 생성하지 않고 Compose 또는 운영자가 준비한 경로만 검증한다.

## 다음 작업

- R1-02에서 liveness와 DB·필수 경로 readiness endpoint를 구현한다.
