# 요약 참조 계약 fingerprint와 API/worker 통합

작성일: 2026-09-08. R8 운영 hotfix의 두 번째 구현 단위.
브랜치/PR 관계: `fix/summary-evidence-timestamps → main`, 087에 이어 같은 hotfix PR에 포함한다.

## 변경과 검증

- prompt_version을 `openai-grounded-summary-v3`, 내부 provider_schema_version을 2로 변경했다.
- `evidence_time_strategy=source-segment-time-v1`을 fingerprint에 포함했다.
- 외부 schema_version/template_version은 1을 유지한다. prompt/schema SHA는 변경된 내용에서 계산한다.
- API와 worker는 기존 공통 fingerprint 계산을 그대로 사용한다. 평가 도구의 기대값도 갱신했다.
- 공개 다섯 범주 및 45분 합성 평가 응답을 시간 없는 참조 계약으로 변경했다.
- 실제 API 등록 → worker 실행 → JSON/Markdown 저장 → HTTP 조회의 원본 시간 일치를 검증했다.
  DB fingerprint를 맞춰주는 우회 없이 API 설정과 실제 어댑터 fingerprint가 일치했다.
- main c346b02의 v2 어댑터에서 model=test, 기본 context의 fingerprint를 계산해
  신버전과 다름을 검증했다. 기준값은 공개 설정만 포함한다.

기존 .venv에서 `pytest backend/tests/unit/test_summary_eval.py
backend/tests/integration/test_summary_requests.py -q`: 25 통과.
`mypy`: 96개 파일 통과, `ruff check backend` 통과.
전체 검사·CI 결과는 089에 기록한다.

## 기존 작업과 결과의 업그레이드 동작

통합 테스트에서 기존 v2 fingerprint의 대기 작업과 완료 작업을 확인했다.

- 기존 대기 작업이 있으면 신설정의 요청은 SUMMARY_IN_PROGRESS로 거절된다.
- 신규 worker는 fingerprint가 다른 작업을 공급자 호출 없이 건너뛴다.
  기존 runtime은 이 반환을 job succeeded로 기록한다. artifact는 생성되지 않으며
  recording은 SUMMARIZING에 남는다. UI summary_status는 failed이고 재요청은 SUMMARY_NOT_READY다.
- 이는 기존 구현의 제한이다. 이번 시간 참조 수정에서 job 상태 계약은 변경하지 않았다.
  **업그레이드 전에 대기/실행 작업을 기존 버전에서 정상 종료해야 한다.**
  남은 작업의 fingerprint를 DB에서 임의 수정하지 않는다.
- 기존 완료 artifact는 보존된다. fingerprint 변경만으로 stale 처리되거나 자동 재요약되지 않는다.
- 완료된 동일 revision에 API로 명시 요청하면 새 fingerprint의 새 job이 생긴다.
  같은 fingerprint로 재요청하면 기존 새 job을 반환한다.
- 일반 revision 변경 시 stale 동작은 기존 통합 회귀로 계속 검사한다.

실제 NVIDIA/GPU 검증은 불필요하다. 호스팅 요약 API의 CPU 경로와 평가/테스트만 변경하며
GPU 런타임을 사용하거나 변경하지 않는다. 운영 배포·유료 호출은 수행하지 않았다.
R8 BLOCKED, R9·R10 NOT STARTED를 유지한다.
