# R9-01 중단 작업 회수·재개

작성일: 2026-09-09. 브랜치: `feature/r9-01-stale-job-recovery → main`.
선행: 094 R8 운영 결과 수용. 후속: R9-02 실패 분류·재시도 UI.

worker는 DB 옆 잠금 파일을 fcntl.flock으로 독점 점유한다. 다른 worker는 migration,
artifact reconciliation, 작업 실행 전에 WORKER_ALREADY_RUNNING으로 종료한다.
프로세스가 SIGKILL로 종료돼도 OS가 잠금을 반환한다. 시간 기반 stale 추정은 하지 않는다.

잠금 확보 후 기존 artifact reconciliation과 running 작업 검사를 수행한다.
DB 등록·해시·schema·recording/revision·segment 내용·비교 가능한 입력 fingerprint를 검증한다.
초기 전사의 input-v1은 콘텐츠 입력 계약이며 모델 fingerprint로 소급하지 않는다.
전사 저장 후 중단되면 기존 segment와 화자 수정을 보존하고 클립·후속 작업만 재개한다.
재전사는 base/target revision을 구분하고 이미 commit한 target을 재전사하지 않는다.
완료된 분류·요약은 검증된 결과와 후속 작업 상태를 사용해 공급자 호출 없이 복구한다.
완료를 증명하지 못하는 화자 처리·render는 입력 검증 후 기존 멱등 실행 경로를 사용한다.

회수와 후속 등록·상태 갱신·audit 기록은 BEGIN IMMEDIATE 트랜잭션으로 묶는다.
미완료 작업은 ID·attempts를 유지해 queued로 반환하고 다음 claim에서 attempts를 증가시킨다.
후속 작업보다 먼저 재개되도록 기존 생성 시각을 실행 가능 시각으로 사용한다.
3회 소진 작업은 실패로 남기되 검증된 완료 결과는 추가 시도 없이 성공 복구한다.
더 최신 revision과 다른 활성 후속 작업의 상태를 과거 실패로 덮어쓰지 않는다.
복구가 요청된 작업은 실행 직전에도 동일 조건을 재검사한다.

검증: backend unit/integration 560개 통과(기존 547 + 복구 회귀 13).
동시 잠금, 프로세스 SIGKILL, checkpoint 재개, 완료 결과 재사용, source 누락·해시 불일치,
revision·설정 충돌, attempts 상한, 후속 중복 방지, 재전사 target 보존을 검사했다.
Python lint/typecheck/format, OpenAPI, frontend format/lint/typecheck/생성 타입,
frontend unit 33개, git diff --check 통과. 구체적 검증·서버 인계는 096에 기록한다.

공개 API·DB schema 변경 없음. 실제 GPU 검증은 미완료이며 서버 결과를 기다린다.
GPU runtime 변경은 없지만 STT·화자 실행 재개 경로가 영향을 받으므로 fake 통과를 실제 GPU
통과로 대신하지 않는다. 다중 호스트·네트워크 파일 시스템 잠금은 지원 범위 밖이다.
