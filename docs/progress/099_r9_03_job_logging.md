# R9-03 작업 추적 로그

작성일: 2026-09-10. 구현·로컬 검증: 2026-09-09.
브랜치: `feature/r9-03-operations-visibility → feature/r9-02-job-retry-ui`.
선행 [PR #57](https://github.com/MiSa-JD/voice_to_document/pull/57), 그 선행 [PR #56](https://github.com/MiSa-JD/voice_to_document/pull/56).

작업 시작 job_started와 성공·실패·자동 재시도 예약 이벤트에 recording_id/job_id/stage/attempt를
동일하게 넣는다. 종료 이벤트에는 monotonic clock으로 측정한 duration_ms를 넣고 실패·예약에는
error_code를 추가한다. R9-01 회수 이벤트도 같은 식별 필드를 제공한다.
요약의 기존 안전한 진단 필드는 유지하고 요약 실패 이벤트에 recording_id를 보강했다.

예상하지 못한 작업 예외와 클립 생성·실패 상태 기록 예외는 원시 traceback을 출력하지 않는다.
JSON formatter에서도 예외 내용 대신 exception_type만 출력해 원문·경로·credential의 노출을 막는다.
작업 로그에는 prompt나 원시 공급자 응답을 추가하지 않았다.

검증: 성공·재시도 예약·영구 실패·예상 밖 실패에서 공통 ID와 정확한 125ms 측정을 확인했다.
민감 값이 든 예외도 JSON 로그에 문자열과 경로를 노출하지 않는 회귀를 추가했다.
전체 Python format/lint/mypy 및 backend 583개 검사가 통과했다. 전체 통합 결과는 100에 기록한다.

이 PR의 변경은 로그·집계·화면이며 GPU 실행 동작·장치·CUDA/NVIDIA runtime을 사용하거나
변경하지 않으므로 별도의 실제 GPU 검증은 불필요하다. 선행 R9-01·02의 실제 GPU 미완료 상태는 유지한다.
