# Flat Obsidian Markdown 출력 검증

> 상태: 자동 검사와 Compose smoke 완료, runtime/GPU 환경 검증 차단

## 통과한 검사

- format, Ruff, mypy, frontend lint/typecheck, OpenAPI 생성물 검사를 통과했다.
- backend unit 256개, integration 15개, frontend unit 9개가 통과했다.
- 제한 sandbox에서 `test_health.py`가 멈췄지만 같은 TestClient test를 host 권한으로 재실행해
  unit health 5개, integration health/API 4개가 통과했다. 전체 suite도 같은 조건에서 통과했다.
- Compose smoke는 공백이 포함된 격리 `DOCUMENT_HOST_DIR`에 flat Markdown 하나만 생성하고,
  하위 디렉터리가 없으며, worker 재시작 뒤 digest가 같음을 확인했다. 브라우저 E2E 3개도 통과했다.

## 환경 차단 항목

- runtime DB에는 기존 recording과 legacy Markdown artifact가 각각 6개 있다. 현재 세션에는 `.env`가
  가리키는 외부 recording/transcript host mount가 존재하지 않아 JSON source 검증이 불가능했다.
  reconciliation은 이전을 시작하지 않았고 기존 파일과 artifact를 보존했다.
- private 다중 화자 fixture는 존재하지만 NVIDIA driver와 통신할 수 없어 실제 GPU pipeline을
  실행하지 못했다.

외부 mount와 NVIDIA runtime이 복구된 환경에서 worker를 시작한 뒤 6건 이전과 private 다중 화자
검증을 다시 실행해야 최종 검증을 완료할 수 있다. transcript 본문과 원본 절대 경로는 기록하지
않았다.
