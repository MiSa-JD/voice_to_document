# R5-07 revision 충돌 UX

## 구현

- 공통 `ApiError`가 HTTP 상태와 함께 서버 오류 `code`, `details`를 보존한다.
- 전체 화자 연결과 발화 일괄 수정에서 `REVISION_CONFLICT`를 일반 실패와 구분해 저장을 중단한다.
- 충돌 시 로컬 draft와 화면의 서버 데이터를 유지하고 최신 revision을 안내한다.
- 사용자가 명시적으로 확인한 경우에만 draft를 폐기하고 최신 서버 상세를 다시 읽는다.

## 검증

- `make check-format`, `make lint`, `make typecheck`, `make api-schema-check` 통과
- `make test-unit`: 297개 통과
- `make test-integration`: 15개 통과
- `make test-frontend`: 16개 통과
- `make compose-smoke`: Compose health, pipeline, worker 재시작과 브라우저 smoke 통과

## 비범위

- 수정 후 artifact 재렌더와 summary 무효화는 R5-08에서 다룬다.
