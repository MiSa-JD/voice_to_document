# R3-09 — CI 기준선

- 기록 번호: 027
- 상태: 완료
- 관련 로드맵: R3-09
- 완료 시각: 2026-08-25T06:32:15Z

## 작업한 내용

- GitHub Actions에 일반 품질·테스트 job과 Compose·Chromium smoke job을 추가했다.
- 일반 job이 Python 3.11, Node 24, uv, FFmpeg를 준비하고 로컬과 같은 Makefile 진입점을 호출하도록 했다.
- format, lint, backend/frontend typecheck, OpenAPI drift, unit, frontend, integration을 CI 필수 흐름에 포함했다.
- Compose job이 frontend 의존성과 Chromium을 준비하고 `make compose-smoke` 하나로 실제 fake E2E를 실행하도록 했다.
- workflow 권한을 repository contents read로 제한했다.

## 검증 결과

- workflow YAML parse와 두 job 이름 확인: 통과
- `git diff --check`: 통과
- CI workflow에 HF token, LLM API key, CUDA, real AI 설정 없음: 확인
- CI가 호출하는 `make compose-smoke`: 로컬 Docker/Chromium에서 통과

## 남은 문제와 결정

- GitHub-hosted runner에서의 실제 workflow 실행은 원격 push 이후에만 확인할 수 있다.
- Compose/E2E를 일반 검사와 분리했지만 두 job 모두 동일 workflow에 포함해 상태를 독립적으로 확인할 수 있게 했다.
- CI를 위한 별도 테스트 명령이나 mock pipeline은 만들지 않았다.

## 다음 작업

- R3 전체 로컬 회귀와 최종 M1 증거를 확인하고 `028_r3_m1_verification.md`에 기록한다.
