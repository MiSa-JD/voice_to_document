# R2-07 — Compose 중복·재시작 검증 완료

- 기록 번호: 018
- 상태: 완료
- 관련 로드맵: R2-07
- 완료 시각: 2026-08-25T05:59:28Z

## 작업한 내용

- 기존 격리 DATA_ROOT `/tmp/voice_to_document_r2.GDQpEf`에서 R2 Compose 검증을 재개했다.
- 동일한 합성 fixture를 `duplicate-name.m4a`라는 다른 이름으로 입력 폴더에 추가했다.
- worker 처리 뒤 동일 콘텐츠가 새 recording이나 job을 만들지 않는지 DB에서 확인했다.
- worker 컨테이너를 재시작하고 완료된 job과 recording 상태가 그대로 유지되는지 확인했다.
- 검증을 마친 api, worker, web 컨테이너와 Compose 전용 network를 정상 종료했다.

## 검증 결과

- 다른 이름의 동일 콘텐츠 처리 후: recordings 1개, jobs 1개, succeeded 1개
- worker 재시작 후: recordings 1개, jobs 1개, succeeded 1개
- backend Ruff format/check: 통과
- backend mypy strict: 통과
- backend unit: 35개 통과
- backend integration: 2개 통과
- frontend Prettier/ESLint/TypeScript: 통과
- frontend unit: 3개 통과
- Compose 종료 및 network 제거: 통과

## 남은 문제와 결정

- Starlette TestClient가 httpx 호환성 변경을 예고하는 deprecation warning 1건을 출력하지만 현재 테스트 결과에는 영향이 없다.
- `/tmp/voice_to_document_r2.GDQpEf`의 합성 입력과 테스트 DB는 사용자 요청 없이 삭제하지 않았다.
- R2 종료 게이트의 구현·검증 증거는 확보했지만 `docs/02_development_roadmap.md`의 체크박스는 수정하지 않았다.

## 다음 작업

- R3-01에서 정규화된 transcript, segment, classification, summary schema와 SQLite migration version 2를 구현한다.
