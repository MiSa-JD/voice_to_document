# R3-03 — 파이프라인 상태 전이 기반

- 기록 번호: 021
- 상태: 완료
- 관련 로드맵: R3-03
- 완료 시각: 2026-08-25T06:04:52Z

## 작업한 내용

- recording의 허용 상태 전이를 단일 표와 DB 연산으로 구현했다.
- 허용되지 않는 전이와 존재하지 않는 recording을 상태 변경 전에 거부하도록 했다.
- FAILED 전이에서만 오류 코드와 사용자용 메시지를 보존하고 정상 전이 시 이전 오류를 지우도록 했다.
- 상태 변경과 후속 job 등록을 같은 SQLite 트랜잭션으로 수행하는 연산을 추가했다.
- job에 input revision과 settings fingerprint를 노출하고 같은 유효 입력의 활성·성공 job을 재사용하도록 했다.
- 최초 transcribe job도 명시적인 input revision과 fingerprint를 기록하도록 했다.

## 검증 결과

- Ruff: 통과
- mypy strict: 통과
- 상태, job claim, recording 저장 단위 테스트: 24개 통과
- 모든 정상 전이 표 기반 저장: 통과
- 대표 불가능 전이 거부: 통과
- 같은 revision/fingerprint 후속 job 한 번만 등록: 통과
- 기존 job claim, 재시도, release 및 recording transaction 회귀: 통과

## 남은 문제와 결정

- 실제 fake 단계 handler와 artifact 생성 연결은 R3-04에서 수행한다.
- 화자 검토를 완료하는 쓰기 API는 R5 범위이므로 R3에서는 SPEAKER_REVIEW 상태에서 안전하게 멈추는 것까지만 처리한다.

## 다음 작업

- R3-04에서 원자적 artifact writer와 fake transcribe/classify/summarize handler를 연결한다.
