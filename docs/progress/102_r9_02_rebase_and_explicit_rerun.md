# R9-02 선행 보강 반영과 명시적 STT 재요청

작성일: 2026-09-10. 브랜치: `feature/r9-02-job-retry-ui`.
base: R9-01 73c7ebd ([PR #56](https://github.com/MiSa-JD/voice_to_document/pull/56)).
이 작업: [PR #57](https://github.com/MiSa-JD/voice_to_document/pull/57). 후속 R9-03.

R9-01 입력 identity·실패 후속 보존 보강을 rebase하고 전체 브랜치 검사를 재실행했다.
backend 583개, frontend 35개, 전체 format/lint/typecheck/OpenAPI/생성 타입/diff 검사 통과.
격리 Compose 기본 브라우저 3개·재시작 보존 1개·회수 probe·재시도 UI 1개도 통과했다.

STT 전용 재수행의 기존 중복 조회는 이미 실패해 힌트가 삭제된 요청까지 차단하고 있었다.
사용자가 언어·힌트를 직접 다시 입력해 명시적으로 요청한 경우, failed 이력은 유지하면서
새 요청을 허용한다. 활성·완료 요청의 중복 방지는 유지하며 삭제된 힌트를 서버가 복원하지 않는다.
회귀에서 동일 옵션을 다시 입력한 새 request_id, 실패 이력 유지, 새 전사 revision 2 완료를
확인했다. 이 추가 API 변경 뒤 위 전체 기본 검사도 다시 통과했다.
최종 head의 Compose/브라우저 검사는 원격 CI에서도 확인한다.

원격 갱신은 --force-with-lease를 사용하며 후속 R9-03을 이 tip 위로 다시 rebase한다.
실제 GPU 검증은 미완료다. 096의 격리 환경과 101의 실제 GPU checkpoint·실패 주입 명령을
서버에서 실행하고 결과를 인계받는다. R6 blocker 및 R9 전체 IN PROGRESS는 유지한다.
