# R3-06 — React 대시보드·상세 화면

- 기록 번호: 024
- 상태: 완료
- 관련 로드맵: R3-06
- 완료 시각: 2026-08-25T06:14:03Z

## 작업한 내용

- 루트 화면을 상태별 개수와 최근 녹음을 보여주는 대시보드로 변경했다.
- `/recordings/:id`에 recording 메타데이터, transcript, category, summary, job 이력을 보여주는 상세 화면을 추가했다.
- 기존 readiness 화면은 `/health` 경로에 유지했다.
- DISCOVERED, TRANSCRIBING, CLASSIFYING, READY_FOR_SUMMARY, SUMMARIZING 상태에서만 3초 polling하도록 했다.
- SPEAKER_REVIEW, COMPLETED, FAILED 상태에서는 polling을 중단하도록 했다.
- loading, empty, API error, 404, success 상태와 재시도 동작을 분리했다.
- 공통 API 오류의 사용자용 message를 fetch client가 표시하도록 했다.
- 키보드 focus, 텍스트 상태 badge, 반응형 dashboard/detail layout을 추가했다.

## 검증 결과

- Prettier: 통과
- ESLint: 통과
- TypeScript strict typecheck: 통과
- React Testing Library: 8개 통과
- production Vite build: 통과
- 대시보드 loading/empty/success/API error/retry: 통과
- 상세 transcript/category/summary/job 표시와 404 구분: 통과

## 남은 문제와 결정

- 전역 상태 관리와 서버 캐시 패키지는 현재 두 읽기 화면에 필요하지 않아 추가하지 않았다.
- 화자 검토, 범주 수정, 요약 요청 같은 쓰기 UI는 해당 API가 도입되는 후속 로드맵에서 구현한다.

## 다음 작업

- R3-07에서 FastAPI OpenAPI snapshot과 프런트엔드 TypeScript 타입을 자동 동기화한다.
