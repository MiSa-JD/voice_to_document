# 응답별 요약 진단과 실행 맥락

## 목적과 변경
082·083에 이어 최초·교정 요청 각각의 시작, 검증 실패, 검증 성공을 기존 JSON logging에 기록했다.
SummaryExecutionContext는 선택적 키워드 인자이며 기존 두 인자 호출은 유지한다.
실제/fake 어댑터, worker, 평가 프로토콜과 호출을 함께 맞췄다.
worker는 logger·job_id·job_attempt·실제 transcript revision을, 공개 평가는 case_id를 전달한다.
호출별 맥락은 지역 변수로 유지하고 공유 어댑터나 전역에 저장하지 않는다.

- 이벤트: summary_request_started / summary_validation_failed / summary_validation_succeeded.
- phase: final_summary / chunk_extraction. provider_attempt는 최초 1, 교정 2.
- chunk_index는 추출 단계의 0 기반 번호다. chunk_count는 추출·최종 병합 단계에 제공한다.
- input_chars는 직접/추출 요청의 segment 본문 글자 수다.
  최종 병합 요청은 실제 전달한 fact.text와 evidence.quote의 글자 수 합계다.
  JSON 구문, 고정 프롬프트, 식별자, 시간 숫자는 포함하지 않는다.
- segment_count는 실제 요청 자료가 포함하거나 근거로 참조하는 고유 segment 수다.
- elapsed_seconds는 각 공급자 요청 시작부터 검증 시점까지 단조 시계로 측정한다.
- 실패 상세는 validation_errors 배열에 validation_type/field_path만 최대 5건 기록한다.
  error_count/omitted_error_count는 전체·생략 건수다.
- 공급자 envelope/전송 실패도 고정 상위 사유로 기록한다. 기존 재시도 정책은 유지한다.

## 검증과 결과
기존 .venv 도구를 직접 사용했다.
- ruff format/check backend: 통과.
- mypy: 95개 파일 통과.
- pytest backend/tests/unit/test_openai_summary.py backend/tests/unit/test_summary_eval.py
  backend/tests/integration/test_summary_requests.py -q: 85 통과.
- 기존 Starlette/httpx deprecation 경고 1건은 이번 변경과 무관하다.

전체/추출의 최초 실패 후 교정 성공, 같은 오류와 다른 오류의 재실패,
evidence 네 사유, 수동 schema 검사, 실제 facts 위치, 입력 규모,
공개 평가 ID, 겹쳐 실행되는 공유 어댑터 호출의 맥락 분리를 검사했다.
실제 worker 처리 흐름에서 작업 시도 2와 공급자 시도 1/2를 구분하고
진단 성공과 job_succeeded의 job_id 연결을 확인했다.
민감한 테스트 문자열이 실제 JsonFormatter 출력, 저장 오류 메시지에 없음을 확인했다.
기존 timeout, 작업 재시도, fingerprint 유지 검사도 통과했다.

## 제한과 GPU
실제 운영 입력의 schema/evidence 원인은 아직 확인하지 않았다. 배포·유료 요청은 별도다.
실제 NVIDIA/GPU 검증은 불필요하다. 호스팅 요약 API의 CPU 진단 경로만 바꾸며
GPU 실행, 의존성, 장치 선택, 컨테이너 런타임에 영향을 주지 않는다.
