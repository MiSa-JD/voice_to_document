# R1-04 — React/TypeScript 골격

- 기록 번호: 008
- 상태: 완료
- 관련 로드맵: R1-04
- 완료 시각: 2026-08-25T05:17:55Z

## 작업한 내용

- React 19, TypeScript strict, Vite, React Router 기반 프런트엔드 골격을 구성했다.
- `/` health 화면과 catch-all 404 화면을 구현했다.
- 상대 경로만 사용하는 공용 JSON fetch client와 readiness client를 구현했다.
- health 화면에서 loading, ready, not-ready(503), network-error 상태와 재시도 동작을 구분했다.
- 44px 조작 영역, 보이는 focus, 텍스트 상태 표현을 포함한 최소 접근성 스타일을 추가했다.
- 개발 Vite server가 `/api`와 `/health`를 로컬 FastAPI로 proxy하도록 설정했다.

## 검증 결과

- Prettier format check: 통과
- ESLint: 통과
- TypeScript project typecheck: 통과
- Vitest/React Testing Library: 3개 테스트 통과
- loading→success, readiness 503, 네트워크 실패→키보드 재시도를 검증했다.
- Vite production build: 통과

## 남은 문제와 결정

- 현재 첫 화면은 R1 health 전용이며 대시보드와 녹음 상세 화면은 R3-06에서 교체한다.
- API 타입은 아직 R1 수동 타입이며 R3-07에서 FastAPI OpenAPI 생성 타입으로 전환한다.

## 다음 작업

- R1-05에서 backend 공용 이미지, Nginx web 이미지, 세 서비스 Compose와 proxy를 연결한다.
