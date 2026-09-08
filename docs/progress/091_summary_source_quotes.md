# 요약 근거 ID 계약과 원본 문장 연결

작성일: 2026-09-08. R8 운영 hotfix의 첫 구현 단위.
브랜치: `fix/summary-source-quotes → main`. 병합된 #54의 후속 독립 PR이다.
기존 090 계획 문서는 당시의 계획 기록으로 보존하고 이 구현과 함께 커밋한다.

## 변경 이유와 구현

공급자가 근거 문장을 다시 작성하면 원문과 일치하지 않아 요약 전체가 실패했다.
공급자 EvidenceReference는 segment_id만 허용하며 quote는 null·부분 인용을 포함해
추가 필드로 거절한다. 시간과 임의 필드의 거절도 유지한다.
공통 resolver가 같은 입력 revision의 원본에서 start_ms, end_ms, text 전체를 연결한다.
전체 요약·chunk 추출·다섯 범주·회의 action_items에 동일하게 적용한다.
입력 transcript와 참조 객체는 변경하지 않으며 UUID 표기 차이는 검증 과정에서 정규화한다.

장문 최종 합성에는 검증된 fact.text와 근거 ID만 전달한다. 원문 quote와 시간을 다시 보내지
않으며 input_chars는 fact.text 길이의 합이다. 분할 segment도 원본 전체 문장과 시간을 쓴다.
공통 최종 검증은 유지하므로 원문을 의역한 최종 quote 직접 주입은 quote_mismatch로 실패한다.
공개 API·OpenAPI·DB·최종 저장 schema는 변경하지 않았다.

## 검증

- `.venv/bin/pytest backend/tests/unit/test_openai_summary.py backend/tests/unit/test_summary_schema.py -q`: 113 통과.
- `.venv/bin/ruff format --check backend`: 97개 파일 통과.
- `.venv/bin/ruff check backend`: 통과.
- `.venv/bin/mypy`: 96개 파일 통과.
- `git diff --check`: 통과.

공개 합성 원문으로 기존 의역 인용 실패를 재현하고 ID 전용 응답의 원문 일치를 확인했다.
quote/null 거절 후 교정 성공, 두 번 실패, schema→evidence 사유 변경, 안전한 오류 경로,
빈 근거·잘못된 자료형·범주, 미등록 ID·chunk 밖 ID, 원본·참조 비변경을 검증했다.
초기 재현 테스트의 예외 문자열 기대를 실제 validation_type 검사로 바로잡은 뒤 재검증했다.

## 남은 범위

fingerprint와 공개 평가·API/worker 통합 회귀는 092, 전체 검사와 운영 인계는 093에 기록한다.
운영 배포·유료 공급자 호출은 수행하지 않았다. 의미적으로 잘못된 ID 선택까지 보장하지 않는다.
실제 NVIDIA/GPU 검증은 불필요하다. 변경한 CPU 요약 경로는 GPU 런타임을 사용하거나 변경하지 않는다.
R8 BLOCKED, R9·R10 NOT STARTED를 유지한다.
