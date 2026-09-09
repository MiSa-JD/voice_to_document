# R8 운영 결과 수용과 R9 착수

작성일: 2026-09-09. 브랜치: `feature/r9-01-stale-job-recovery → main`.
기준 main: `2f126c5`, PR #55 병합. 원격 main과 일치하며 시작 당시 열린 PR과 미커밋 변경 없음.

사용자는 대부분의 요약 요청이 운영 서버에서 생성·조회까지 성공함을 확인했다.
대량 동시 등록이나 긴 대화에서 간헐적인 `SUMMARY_INVALID_OUTPUT`을 관측했으나,
정확한 발생률과 원인은 미확정이다. 추가 요약 수정에 이미 많은 시간을 사용했으므로
알려진 제한을 수용하고 복구·재시도·운영 정보 개선을 먼저 진행한다.
R8 DONE은 모든 요약 오류 해결을 뜻하지 않는다. R6 모델 접근 승인·평가 표본 blocker는 유지한다.
R9는 IN PROGRESS이며 R9-03 완료만으로 R9 전체를 완료 처리하지 않는다.

스택 순서는 `feature/r9-01-stale-job-recovery → main`,
`feature/r9-02-job-retry-ui → feature/r9-01-stale-job-recovery`,
`feature/r9-03-operations-visibility → feature/r9-02-job-retry-ui`다.
각 브랜치 전체 검사 후 커밋·한국어 PR을 게시하고 병합하지 않는다.

검증: git status, 원격 fetch, main 커밋 및 열린 PR 조회로 시작 상태를 확인했다.
문서 변경 자체는 GPU runtime에 영향을 주지 않아 실제 GPU 검증이 불필요하다.
R9-01·02는 실제 GPU 실행 경로에 영향을 주므로 fake 검증과 별도로 서버 명령을 인계하고
사용자 결과를 받을 때까지 실제 GPU 검증 미완료로 표시한다.

요약 프롬프트·모델·분할·검증 완화·자동 재시도 확대는 제외한다.
실패 빈도가 운영에 지장을 주거나 재현 가능한 사례를 확보하면 별도 후속 작업으로 다룬다.
R9-04 이후 백업·보안·전체 접근성·종합 E2E·운영 문서 완성도 남겨 둔다.
