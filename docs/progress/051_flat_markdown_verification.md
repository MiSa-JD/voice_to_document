# Flat Obsidian Markdown 출력 검증

> 상태: 자동 검사, Compose smoke, 실제 GPU 검증 완료; runtime 기존 6건 이전은 mount 대기

## 통과한 검사

- format, Ruff, mypy, frontend lint/typecheck, OpenAPI 생성물 검사를 통과했다.
- backend unit 256개, integration 15개, frontend unit 9개가 통과했다.
- 제한 sandbox에서 `test_health.py`가 멈췄지만 같은 TestClient test를 host 권한으로 재실행해
  unit health 5개, integration health/API 4개가 통과했다. 전체 suite도 같은 조건에서 통과했다.
- Compose smoke는 공백이 포함된 격리 `DOCUMENT_HOST_DIR`에 flat Markdown 하나만 생성하고,
  하위 디렉터리가 없으며, worker 재시작 뒤 digest가 같음을 확인했다. 브라우저 E2E 3개도 통과했다.
- sandbox 밖에서 호스트와 Docker가 모두 RTX 3060 12GB와 driver `535.309.01`을 정상 인식함을
  확인했다.
- private 다중 화자 fixture를 실제 GPU worker로 처리했다. schema v2 JSON과 flat Markdown의
  recording identity 및 revision 1이 일치했고, timestamp가 포함된 segment 144개와
  `SPEAKER_XX` 화자 2명을 확인했다. worker 재시작 뒤 Markdown digest도 유지됐다.

## 환경 차단 항목

- runtime DB에는 기존 recording과 legacy Markdown artifact가 각각 6개 있다. 현재 세션에는 `.env`가
  가리키는 외부 recording/transcript host mount가 존재하지 않아 JSON source 검증이 불가능했다.
  reconciliation은 이전을 시작하지 않았고 기존 파일과 artifact를 보존했다.
외부 mount가 연결된 환경에서 worker를 시작해 기존 6건 이전을 다시 실행해야 runtime 이전
검증을 완료할 수 있다. transcript 본문과 원본 절대 경로는 기록하지 않았다.
