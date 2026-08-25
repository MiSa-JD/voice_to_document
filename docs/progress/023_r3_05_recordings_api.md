# R3-05 — 녹음 목록·상세 API

- 기록 번호: 023
- 상태: 완료
- 관련 로드맵: R3-05
- 완료 시각: 2026-08-25T06:10:26Z

## 작업한 내용

- 최신 생성 순서와 50개 고정 page size를 사용하는 `GET /api/recordings`를 추가했다.
- 목록 API에 recording 상태와 허용 category filter, 필터 결과 개수, 전체 상태별 개수를 추가했다.
- recording, 시간순 segments, artifacts, 최신순 jobs, 정규화 summary를 반환하는 `GET /api/recordings/{id}`를 추가했다.
- 모든 정상 응답을 Pydantic response model로 선언해 FastAPI OpenAPI의 기준 계약으로 만들었다.
- 존재하지 않는 recording, 잘못된 filter, 요청 validation에 공통 `error.code/message/details` 응답을 적용했다.
- source path와 내부 stack trace를 공개 응답에서 제외하고 summary artifact 경로가 설정 root 안인지 확인하도록 했다.

## 검증 결과

- Ruff: 통과
- mypy strict: 통과
- recordings API 및 health 회귀 테스트: 8개 통과
- 빈 목록과 모든 상태 개수 0 응답: 통과
- COMPLETED/회의 filter, 최신 상세 segments/artifacts/jobs/summary: 통과
- source path 비노출: 통과
- 404 RECORDING_NOT_FOUND, 422 INVALID_CATEGORY/INVALID_REQUEST: 통과

## 남은 문제와 결정

- R3 목록은 고정 50개로 충분하므로 cursor pagination은 추가하지 않았다. 실제 데이터가 50개를 넘고 탐색 요구가 생기면 확장한다.
- 쓰기 API와 별도 segment pagination은 화자·수정 작업이 시작되는 후속 로드맵에서 구현한다.

## 다음 작업

- R3-06에서 API 계약을 사용하는 React 대시보드와 녹음 상세 화면을 구현한다.
