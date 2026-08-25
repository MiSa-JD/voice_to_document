# R3-07 — OpenAPI 타입 동기화

- 기록 번호: 025
- 상태: 완료
- 관련 로드맵: R3-07
- 완료 시각: 2026-08-25T06:16:27Z

## 작업한 내용

- 임시 절대 경로 설정으로 FastAPI OpenAPI를 결정적으로 생성하는 `app.openapi` 명령을 구현했다.
- 정렬된 루트 `openapi.json` snapshot과 생성된 `frontend/src/api/schema.d.ts`를 추가했다.
- 이미 설치된 `openapi-typescript` Node API를 사용해 TypeScript 타입을 생성·검사하는 스크립트를 추가했다.
- 프런트엔드 recording API 타입을 수동 interface에서 생성된 OpenAPI components alias로 교체했다.
- `make api-schema`는 snapshot과 타입을 명시적으로 갱신하고, `make api-schema-check`는 파일을 수정하지 않고 두 drift를 검사하도록 했다.
- Node용 생성 스크립트가 frontend lint에 포함되도록 ESLint 실행 환경을 명시했다.

## 검증 결과

- backend Ruff 및 mypy strict: 통과
- frontend Prettier, ESLint, TypeScript strict: 통과
- `make api-schema-check`: OpenAPI snapshot과 TypeScript 타입 모두 통과
- 생성 타입을 사용하는 React 테스트: 8개 통과

## 남은 문제와 결정

- 별도 API SDK나 runtime client generator는 현재 두 GET 요청에 필요하지 않아 추가하지 않았다.
- OpenAPI 생성 시 API 구성 로그 1건이 출력되지만 snapshot 내용에는 포함되지 않고 비밀값도 노출하지 않는다.

## 다음 작업

- R3-08에서 깨끗한 Compose DATA_ROOT와 실제 Playwright Chromium으로 입력부터 상세 결과까지 E2E를 검증한다.
