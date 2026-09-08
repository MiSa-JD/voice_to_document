# 요약 원문 연결 fingerprint와 실행 호환성

작성일: 2026-09-08. R8 운영 hotfix의 두 번째 구현 단위.
브랜치/PR: `fix/summary-source-quotes → main`. 091과 같은 독립 hotfix PR에 포함한다.

## 변경과 검증

- prompt_version을 `openai-grounded-summary-v4`, provider_schema_version을 3으로 올렸다.
- `evidence_quote_strategy=source-segment-text-v1`을 추가하고 시간 전략
  `source-segment-time-v1`과 외부 schema_version/template_version=1은 유지했다.
- 실제 지시문과 다섯 범주 JSON schema에서 계산한 SHA 및 이전 main 0a33cb9와의 차이를 검증했다.
- 공개 평가의 fingerprint 기대값과 테스트 transport 응답을 ID 전용 계약으로 변경했다.
- API가 등록한 fingerprint를 DB에서 덮어쓰지 않고 실제 어댑터를 worker에 연결해
  요청 → JSON/Markdown 생성 → HTTP 조회를 확인했다. 짧은 문장과 약 2.6만 자 원문 모두
  저장·조회 quote가 해당 revision의 원본 전체와 일치했다. Markdown은 기존 ID·시간 표기를 유지한다.
- 장문 최종 합성에는 fact.text와 ID만 전달하며 input_chars는 fact.text 길이 합으로 검증한다.
- 공유 어댑터에서 동일 segment ID와 서로 다른 revision·원문을 동시에 처리해 원문 연결과
  job/revision 진단 맥락이 섞이지 않음을 확인했다. 로그에는 원문·credential을 기록하지 않는다.

`.venv/bin/pytest backend/tests/unit/test_openai_summary.py backend/tests/unit/test_summary_eval.py
backend/tests/integration/test_summary_requests.py backend/tests/integration/test_summary_stale.py -q`:
136 통과. 공개 다섯 범주 및 45분 합성 평가를 포함하며 실제 유료 공급자 호출은 없다.
`.venv/bin/ruff check backend`, `.venv/bin/mypy`: 통과(96개 source 파일).
초기 호환성 fixture의 quote가 이미 null인 점을 반영해 부분 인용은 원본에서 구성하도록 수정했다.

## 업그레이드 호환성과 운영 제한

기준 main 0a33cb9의 공개 model=test 기본 설정으로 구버전 fingerprint를 직접 계산했다.
구버전 대기 작업은 신설정 요청을 SUMMARY_IN_PROGRESS로 막고, 신버전 worker는 공급자 호출 없이
건너뛴다. 기존 runtime이 job을 succeeded로 기록해도 artifact가 없고 recording은 SUMMARIZING에
남는다. UI summary_status=failed, 재요청 SUMMARY_NOT_READY인 기존 제한은 그대로다.
업그레이드 전 기존 대기/실행 작업을 정상 종료해야 하며 DB fingerprint를 임의로 바꾸지 않는다.

기존 완료 artifact는 부분 인용과 null을 포함한 파일 바이트·DB 행·HTTP 조회 값이 보존된다.
fingerprint 변경만으로 stale 표시나 자동 일괄 재요약이 발생하지 않는다.
동일 revision에 명시 요청하면 새 fingerprint 작업이 생기며 중복 요청은 그 작업을 재사용한다.
revision 변경에 따른 기존 stale 정책도 통합 회귀로 검증했다.

운영 배포·유료 요청·재시도 정책·timeout·모델·작업 상태 처리는 변경하지 않았다.
실제 NVIDIA/GPU 검증은 불필요하다. 변경한 CPU 경로는 GPU 런타임을 사용하거나 변경하지 않는다.
전체 검사와 서버 인계는 093에 기록하며 R8 BLOCKED, R9·R10 NOT STARTED를 유지한다.
