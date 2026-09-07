# 요약 세부 검증 로그 추가 및 운영 실패 진단 계획

## 결론과 문서 상태

**기존 로그를 더 수집하는 명령만으로는 원인을 확정할 수 없다. 세부 검증 로그 기능을 먼저 추가해야 한다.**
현재 `schema`·`evidence` 로그는 최종 교정 응답이 실패한 단계만 알려 준다.
실패 필드, 근거 불일치 종류, 최초 응답과 교정 응답의 차이는 기록하지 않는다.
기록되지 않은 정보를 서버 로그 조회 명령으로 복구할 수는 없다.

이 문서는 구현 계획이다. 이번 문서 작성에서는 코드 수정, 서버 배포·재시작,
유료 API 재요청, Git 커밋·push·PR 게시를 수행하지 않는다.
진단 기능 구현 완료와 운영 요약 문제 해결 완료를 별도 조건으로 관리한다.

## 확보한 증거와 한계

운영 사례는 식별자나 비공개 내용을 넣지 않고 A/B로 구분한다.

| 항목 | 사례 A | 사례 B |
| --- | --- | --- |
| 최종 검증 사유 | evidence | schema |
| 녹음 길이 | 약 4분 6초 | 약 47분 45초 |
| 실패 job 입력 revision | 2 | 2 |
| 조회 시 recording revision | 2 | 3 |
| 조회 시 범주 | 기타 | 강의 |
| 조회 시 segment / 본문 글자 수 | 22개 / 1,284자 | 378개 / 16,815자 |

- A는 짧은 입력에서도 실패했다. 장문 timeout만으로 두 사례를 설명할 수 없다.
- B의 현재 segment와 범주는 실패한 revision 2의 입력을 증명하지 않는다.
  진단 시 실제 요청에 사용한 revision과 template을 반드시 기록해야 한다.
- 현재 worker는 real document 모드, 요약 timeout 300초, context 기준 120,000자다.
  현재 컨테이너 생성 시점은 해당 실패보다 나중이므로 실패 당시 설정의 직접 증거는 아니다.
- 재생성된 현재 컨테이너에서 이전 job 로그가 조회되지 않았다.
  재현 로그는 다음 재생성 전에 수집해야 한다.
- 081의 공개 합성 45분 평가 성공은 유효하지만 운영 사례의 해결 증거를 대체하지 않는다.

## 목표와 비범위

목표는 한 번의 수동 요약 재요청으로 다음을 구분할 수 있게 하는 것이다.

1. 어떤 revision·template·입력 규모로 어느 요약 단계가 실행됐는가.
2. 최초 응답과 교정 응답 각각에서 어떤 검증 항목이 실패했는가.
3. 교정 후 성공했는가, 같은 오류 또는 다른 오류로 최종 실패했는가.
4. 민감한 입력이나 공급자 원문 없이 수정 대상을 특정할 수 있는가.

이번 진단 변경에서는 timeout, 최대 job 시도 수, 교정 요청 횟수, 프롬프트,
모델, chunk 기준, schema 허용 범위, evidence 통과 기준을 바꾸지 않는다.
검증을 느슨하게 해서 통과시키거나 실패한 운영 job을 일괄 재실행하지 않는다.
HTTP API와 DB schema, GPU 경로도 변경하지 않는다.
실제 원인이 확인되면 근본 수정과 회귀 테스트 범위를 별도로 정한다.

## 구현 순서

### 1. 검증 오류를 안전한 구조로 표현

주요 대상: `backend/app/schema.py`, `backend/app/summary.py`,
`backend/app/openai_summary.py`.

- 예외 문자열을 해석하지 않고 검증이 실패한 분기에서 고정된 사유를 지정한다.
- evidence 사유는 `unknown_segment`, `timestamp_mismatch`, `quote_mismatch`,
  `outside_chunk`로 구분한다.
- 전체 요약의 evidence 검증과 chunk별 허용 segment 검증에 같은 분류 기준을 적용한다.
- schema 오류는 Pydantic 오류의 안전한 유형과 허용된 필드 경로만 추출한다.
  예: `key_facts[0].evidence` + `missing`.
- 유효한 JSON이지만 객체가 아닌 결과, 빈 facts 목록 등 수동 검사도 고정된 유형으로 표현한다.
- 기존 `ValueError`를 잡는 호출부와의 호환성을 확인한다. 새 예외가 필요하면
  기존 검증 흐름에 맞는 최소 확장만 사용하고 모든 호출부를 점검한다.
- 외부 `SUMMARY_INVALID_OUTPUT` 코드는 유지한다.

### 2. 각 응답의 검증 결과와 실행 맥락을 기록

주요 대상: `backend/app/openai_summary.py`, `backend/app/pipeline.py`,
`backend/app/summary_eval.py`.

최종 오류를 던질 때만 기록하면 최초 실패 후 교정 성공 사례가 사라진다.
따라서 전체 요약과 chunk 추출의 각 검증 시점에서 기록한다.
기존 logging을 재사용하며 새 진단 저장소나 외부 서비스를 추가하지 않는다.

| 필드 | 의미 |
| --- | --- |
| event | `summary_request_started`, `summary_validation_failed`, `summary_validation_succeeded` |
| job_id | worker 실행 시 해당 작업과 연결하는 기존 내부 식별자 |
| input_revision | 실제 요약에 사용한 transcript revision |
| template | 실제 사용한 고정 template 이름 |
| phase | `final_summary` 또는 `chunk_extraction` |
| chunk_index / chunk_count | chunk 경로일 때만 기록, 0부터 시작하는 index로 통일 |
| job_attempt | worker의 job 시도 번호 |
| provider_attempt | 해당 전체 요약 또는 chunk의 최초 요청 1 / 교정 요청 2 |
| input_chars / segment_count | 실제 요청 자료의 본문 글자 수와 segment 수 |
| elapsed_seconds | 해당 공급자 요청 시작부터 검증 결과까지의 시간 |
| failure_reason | 기존 `schema`, `evidence` 등 상위 분류 |
| validation_type | 안전한 세부 검증 사유 |
| field_path | 허용된 schema 필드명과 숫자 index로만 구성한 위치 |

- 전체 요청과 chunk 내부의 번호를 구분해 여러 chunk의 `provider_attempt=1`이 혼동되지 않게 한다.
- worker job 맥락은 호출별로 전달하고 공유 전역 상태에 저장하지 않는다.
- 평가 진입점은 job_id 없이 공개 case_id로 연결한다. 프로토콜·호출부 변경은 최소화한다.
- 교정 성공이면 성공 이벤트와 기존 `job_succeeded`가 연결돼야 한다.
- 로그 전용 변경은 요약 내용 fingerprint를 변경하지 않아야 한다.

로그 형태 예시이며 아직 구현된 이벤트는 아니다.

```json
{"event":"summary_validation_failed","phase":"final_summary","input_revision":2,"template":"other","job_attempt":1,"provider_attempt":2,"failure_reason":"evidence","validation_type":"timestamp_mismatch","field_path":"key_facts[0].evidence[0]"}
```

### 3. 민감정보와 로그 크기 제한

- transcript, 공급자 응답, quote, 실제 필드 값, API key, 비공개 source/artifact 경로는 기록하지 않는다.
- `str(ValidationError)`, 예외 traceback, Pydantic `input`·`ctx`·자유 형식 `msg`를 출력하지 않는다.
- Pydantic 오류를 가져올 때 input/context/url을 제외하고, 출력은 다시 허용 목록으로 구성한다.
- 오류 `loc`에 공급자가 만든 알 수 없는 키가 들어갈 수 있으므로 필드 경로도 검증한다.
  알 수 없는 문자열 경로 조각은 고정된 대체값으로 바꾼다.
- 오류 유형 역시 알려진 값만 출력하고 알 수 없는 유형은 고정값으로 대체한다.
- 다수 schema 오류는 응답당 최대 5건만 출력하고 전체 개수·생략 개수를 숫자로 남긴다.
- 시간 불일치 판별에 실제 타임스탬프 값이 필수는 아니므로 초기 진단에는 출력하지 않는다.

### 4. 로컬 회귀 테스트

- schema: 필수 필드 누락, 자료형 오류, 값 제약, 객체가 아닌 JSON, 빈 facts 목록.
- evidence: 없는 segment, 시간 불일치, 인용문 불일치, chunk 밖 segment 참조.
- 전체 요약과 chunk 경로 각각에서 최초 실패 → 교정 성공 및 두 번 실패를 검증한다.
- 최초와 최종 오류 사유가 다른 경우 두 이벤트가 각각 정확히 남는지 확인한다.
- worker의 job_id·revision·job_attempt와 공급자의 provider_attempt 연결을 검증한다.
- 평가 도구에서도 같은 안전한 진단을 받을 수 있는지 확인한다.
- transcript·응답·키·비공개 경로·예외 메시지·알 수 없는 JSON 키에 테스트용 민감 문자열을 넣고,
  구조화 로그 및 저장 오류 메시지에 노출되지 않는지 검사한다.
- 오류 수 제한과 생략 개수, fingerprint 유지도 검증한다.
- 기존 timeout 재시도 상태 회귀 테스트를 유지한다.

구현 완료 시 저장소 기본 format/lint/typecheck/API schema/unit/integration/frontend 검사와
`git diff --check`를 수행한다. 기존 `.venv`가 있으면 그 안의 도구를 사용하며
Makefile의 `uv run` 뒤 명령을 직접 실행한 경우 실행 방식을 기록한다.
실제 NVIDIA/GPU 검증은 불필요하다. 변경 경로가 GPU 실행이나 런타임에 영향을 주지 않는다.

## 운영 재현 절차와 담당 구분

### 구현자가 먼저 할 일

1. 세부 진단 기능과 회귀 테스트를 구현한다.
2. 검증된 커밋과 배포 방법, 새 이벤트 필드만 출력하는 복사·붙여넣기용 로그 수집 명령을 제공한다.
3. 로그 수집 명령은 키·원문·예외 전체가 출력되지 않도록 허용 목록을 사용한다.
4. 진단 기능이 배포되기 전에는 사용자에게 동일한 기존 로그를 반복 수집하도록 요청하지 않는다.

### 진단 기능 배포 후 운영에서 할 일

1. 실제 실행 이미지와 해당 커밋의 대응을 확인하고 worker를 갱신한다.
2. 사례 A가 여전히 같은 revision인지 확인한 뒤 기존 UI에서 수동 요약을 한 번 재요청한다.
   API 비용이 발생한다. 이번 계획 문서 작성에는 배포나 유료 재요청 실행이 포함되지 않는다.
3. 새 job_id로 최초 응답·교정 응답·최종 결과를 수집한다.
   이전 실패 job_id로 검색하면 새 재요청 결과를 찾을 수 없다는 점을 안내한다.
4. 원인이 확인되면 같은 입력을 반복 요청하지 않고 해당 실패 유형의 공개 회귀 입력을 만든다.
5. 사례 B는 현재 revision 3을 평가하는지, 보존된 revision 2를 별도 재현하는지 먼저 구분한다.
   DB revision을 되돌리거나 운영 원문을 공개 fixture로 복사하지 않는다.
6. B의 추가 실제 요청은 A의 진단으로 부족한 항목이 있을 때 목적과 입력 revision을 정해 실행한다.

## 완료 조건과 후속 수정 판단

### 진단 기능 완료

- 최초/교정 응답과 전체/chunk 단계를 구분한다.
- 원문 없이 schema의 필드·유형과 evidence의 세부 사유를 확인할 수 있다.
- 실패 후 교정 성공도 기록되며 기존 상태 처리·fingerprint·검증 기준을 유지한다.
- 관련 회귀 및 저장소 기본 검사가 통과한다.
- 사용자가 바로 실행할 안전한 운영 로그 수집 명령을 제공한다.

### 운영 문제 해결 완료

진단 기능 추가만으로 운영 문제 해결을 선언하지 않는다.
실패 원인에 맞는 수정, 해당 원인을 재현하는 테스트, 운영 재검증 결과가 필요하다.
예를 들어 모델이 segment ID를 정확히 선택하지만 시간을 잘못 복사하는 것으로 확인되면,
근거 시간 생성 책임을 모델에서 서버로 옮길지 검토할 수 있다.
그러나 이를 원인 확인 전에 적용하거나 잘못된 인용문을 무조건 버려 통과시키지는 않는다.

R8 완료 게이트는 운영 실패의 수정·검증·병합 전까지 열어 두며 R9 착수와 구분한다.

## 구현 착수 시 PR 계획

- 문서 작성 시 로컬은 기존 hotfix 브랜치이며 사용자 서버는 그보다 이후의 main이다.
  서버 main에 어떤 PR이 병합됐는지는 현재 로컬 정보만으로 확정하지 않는다.
- 구현 착수 시 최신 원격 main과 기존 hotfix의 병합 여부를 확인한다.
- 진단 기능을 하나의 독립 운영 hotfix PR로 묶는 것을 기본으로 한다.
  예정 관계: `fix/summary-validation-diagnostics` → 최신 `main`, 선행·후속 stack 없음.
- 기존 hotfix가 아직 병합되지 않았다면 필요한 코드가 main에 있는지 확인해 base 관계를 조정하고
  구현 전에 알린다. 기존 브랜치나 다른 진행 작업을 임의로 변경하지 않는다.
- PR 제목·본문·검증 결과는 한국어로 작성하고 자동 병합하지 않는다.
