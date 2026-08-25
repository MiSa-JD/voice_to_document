# R1-03 — worker 골격

- 기록 번호: 007
- 상태: 완료
- 관련 로드맵: R1-03
- 완료 시각: 2026-08-25T05:15:44Z

## 작업한 내용

- API와 같은 Python 패키지에서 `python -m app.worker`로 실행되는 worker 엔트리포인트를 구현했다.
- 시작 전에 공통 설정과 SQLite 연결 준비 상태를 확인하도록 했다.
- SIGTERM과 SIGINT를 event로 전달해 대기 중인 worker가 즉시 정상 종료하도록 했다.
- 시작, 종료 요청, 종료 이벤트에 `service=worker`와 stage/signal 문맥을 포함했다.

## 검증 결과

- `ruff check`: 통과
- 전체 백엔드 `mypy --strict`: 통과
- 실제 subprocess worker에 SIGTERM을 보내 3초 안에 종료 코드 0으로 끝나는 테스트: 통과
- 구조화 로그의 세 이벤트와 `service=worker` 필드 검증: 통과

## 남은 문제와 결정

- R1 worker는 아직 입력 scan이나 job 처리를 하지 않는다.
- 실행 중 job의 안전한 반환과 claim은 R2-06에서 추가한다.

## 다음 작업

- R1-04에서 React Router, 상대 경로 fetch client, health 상태 화면을 구현한다.
