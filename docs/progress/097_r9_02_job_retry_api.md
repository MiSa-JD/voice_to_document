# R9-02 실패 정책과 수동 재시도 API

작성일: 2026-09-09. 브랜치: `feature/r9-02-job-retry-ui`.
base: `feature/r9-01-stale-job-recovery` ([선행 PR #56](https://github.com/MiSa-JD/voice_to_document/pull/56)).
후속: R9-03 운영 현황. 선행 최종 head 003ac9e의 quality-and-tests와 compose-smoke 통과 확인.

작업 조회는 음성 처리 정책과 분류·요약 정책을 연결해 transient/action_required/invalid_output/
internal 분류와 안전한 한국어 설명을 반환한다. queued의 next_run_at, 자동 재시도 상태,
실제 recovery_action과 불가 사유도 서버가 제공한다. attempts만으로 오류 성격을 추정하지 않는다.
원시 error_message 대신 정책 설명을 반환하며 기존 자동 최대 3회·지수 backoff는 변경하지 않는다.
SUMMARY_INVALID_OUTPUT은 자동 재시도 대상으로 확대하지 않는다.

POST /api/recordings/{id}/retry는 job_id와 expected_revision을 받는다.
BEGIN IMMEDIATE 안에서 소유 관계, 실패 상태, 현재 revision, 활성 작업, 입력 무결성과
설정을 확인한다. R9-01 inspect_recovery를 재사용하고, 공급자 호출·GPU 모델 로딩은 하지 않는다.
실패 이력을 보존한 새 job과 새 자동 시도 예산을 등록하며 audit로 원 작업을 연결한다.
동시 요청은 같은 child job을 반환하고 created=false로 중복 등록을 막는다.
오래된 revision·실행 불가 상태는 409, 소유하지 않은 작업은 404다.

요약은 기존 요약 재요청을 안내하고, STT 재수행 실패는 언어·힌트를 새로 입력하는 기존 전용
기능으로 연결한다. 최종 실패로 삭제된 힌트를 복원하거나 힌트 없는 동일 재수행을 만들지 않는다.
OpenAPI와 frontend 생성 타입을 함께 갱신했다.

검증: 재시도 통합 회귀 17개 통과. 동시에 두 번 요청해도 child는 하나, 실패 이력 유지,
새 attempts=1, source 누락·revision·설정·상태 충돌 거절, 요약·재전사 전용 경로,
힌트 삭제 유지, 자동 대기 시각·소진·출력 오류 비재시도 정책을 확인했다.
Python lint/mypy/OpenAPI 통과. 전체 검사와 브라우저 결과는 098에 기록한다.
실제 GPU 검증은 미완료이며 096의 격리 서버 인계 절차를 따른다.
