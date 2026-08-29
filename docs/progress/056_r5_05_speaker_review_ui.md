# R5-05 화자 검토 React 화면

## 구현

- 녹음 상세 응답에 화자별 인물 배정, 출처/유사도, 발화 수/시간, 대표 클립 상태와 위치를 추가했다.
- 원본 오디오와 대표 클립을 들으며 기존 인물, 새 인물, 알 수 없음으로 화자 전체를 즉시 배정할 수 있다.
- 화자 선택 시 해당 transcript 발화를 강조하고 timestamp로 원본 오디오를 탐색한다.
- `design.md`의 Amber & Earth 토큰을 공통 CSS 변수로 적용했다.

## 검증

- `make check-format`, `make lint`, `make typecheck`, `make api-schema-check` 통과
- `make test-unit`: 297개 통과
- `make test-integration`: 15개 통과
- `make test-frontend`: 12개 통과
- `make compose-smoke`: Compose health, pipeline, worker 재시작과 브라우저 smoke 통과

## 비범위

- 발화 개별/일괄 draft 수정은 R5-06에서 다룬다.
- revision 충돌 전용 UX는 R5-07에서 다룬다.
- 자동 후보 산정은 R6 범위다.
