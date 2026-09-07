# 요약 검증 오류 분류

## 목적과 변경
082 계획에 따라 원문 없이 schema/evidence 실패를 식별한다.
ValueError 하위 예외에 고정 유형과 실제 응답 필드 위치를 추가했다.
전체 요약과 chunk는 공통 근거 검증을 사용하고, chunk 위치는 facts 배열을 기준으로 한다.
근거 전체 검증 후 chunk 소속을 확인하는 기존 순서와 통과 기준을 유지했다.
Pydantic 오류는 허용 필드·유형만 추출하며 5건 제한과 전체·생략 건수를 제공한다.
기존 082 계획 문서는 변경 없이 보존한다.

## 검증
기존 .venv의 도구를 직접 사용했다.
- ruff check/format: 변경 파일 통과.
- pytest backend/tests/unit/test_summary_schema.py backend/tests/unit/test_openai_summary.py -q: 47 통과.
- mypy: 95개 파일 통과.
필수 필드, 자료형, 길이 제약, 네 가지 evidence 사유, 미지 키·유형 대체, 오류 수 제한을 확인했다.

## 제한과 후속
응답별 이벤트와 worker·평가 맥락 연결은 다음 작업에서 수행한다.
외부 오류 코드, 프롬프트, schema, fingerprint는 변경하지 않았다.
실제 NVIDIA/GPU 검증은 불필요하다. 변경 경로는 GPU 실행이나 런타임에 영향을 주지 않는다.
