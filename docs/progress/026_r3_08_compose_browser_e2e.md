# R3-08 — Compose·브라우저 E2E

- 기록 번호: 026
- 상태: 완료
- 관련 로드맵: R3-08
- 완료 시각: 2026-08-25T06:30:36Z

## 작업한 내용

- 매 실행마다 전용 임시 DATA_ROOT를 만들고 api, worker, web을 빌드·기동하는 Compose smoke 스크립트를 추가했다.
- 스크립트가 호스트 web endpoint readiness를 확인한 뒤 E2E를 시작하고 성공·실패와 관계없이 Compose와 자신이 만든 임시 디렉터리를 정리하도록 했다.
- 완료 fixture를 실제 inbox에 복사하고 API에서 COMPLETED를 확인한 뒤 대시보드와 상세 화면을 Chromium으로 검증했다.
- worker를 재시작한 뒤 같은 recording, 3개 succeeded job, 4개 artifact와 상세 화면이 유지되는지 검증했다.
- Playwright를 상태 공유에 맞게 단일 worker로 고정했다.
- 프런트엔드 `/health` 경로와 Nginx `/health/` API proxy의 redirect 충돌을 발견해 readiness 화면을 `/service-status`로 이동했다.
- root 대시보드, service status, API 404, React 404를 실제 브라우저에서 함께 검증했다.

## 검증 결과

- Compose api/worker/web build 및 health: 통과
- 실제 Playwright Chromium health/dashboard/404: 1개 통과
- fixture 입력부터 dashboard/detail transcript/category/summary: 1개 통과
- worker 재시작 후 DB/API/UI 보존: 1개 통과
- 완료 결과: recordings 1개, jobs 3개 모두 succeeded, artifacts 4개
- smoke 종료 후 Compose 서비스·network와 전용 `voice-to-document-smoke.*` 디렉터리 정리: 통과
- frontend Prettier, ESLint, TypeScript: 통과

## 남은 문제와 결정

- 인앱 브라우저 runtime 목록이 비어 있어 사용할 수 없었고, 실제 설치된 Playwright Chromium을 검증 수단으로 사용했다.
- 첫 실패들에서 pipeline E2E는 계속 통과했으며, health UI 경로만 Nginx proxy redirect와 충돌했다. 충돌 경로를 수정한 최종 smoke에서는 retry 없이 모두 통과했다.
- 기존 `/tmp/voice_to_document_r2.GDQpEf`는 수정하거나 삭제하지 않았다.

## 다음 작업

- R3-09에서 로컬 Makefile 진입점을 그대로 호출하는 GitHub Actions CI 기준선을 추가한다.
