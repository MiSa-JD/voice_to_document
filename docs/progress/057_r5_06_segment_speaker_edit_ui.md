# R5-06 발화 개별/일괄 수정

## 구현

- transcript 발화를 개별 또는 여러 개 선택해 기존 인물, 새 인물, 알 수 없음으로 바꾸는 로컬 draft를 추가했다.
- 저장 전에 대상 발화 수와 기존/변경 화자를 확인하며 한 번의 batch API 호출로 저장한다.
- 저장 중 중복 제출을 막고 성공 후 draft를 비운 뒤 최신 revision을 다시 읽는다.
- 저장하지 않은 draft가 있으면 브라우저 종료와 녹음 상세 이동을 경고하며, 명시적 폐기 전에는 서버를 바꾸지 않는다.

## 검증

- `make check-format`, `make lint`, `make typecheck`, `make api-schema-check` 통과
- `make test-unit`: 297개 통과
- `make test-integration`: 15개 통과
- `make test-frontend`: 14개 통과
- `make compose-smoke`: Compose health, pipeline, worker 재시작과 브라우저 smoke 통과

## 비범위

- revision 충돌 전용 안내와 최신 서버 데이터 재로딩은 R5-07에서 다룬다.
