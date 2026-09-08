# 요약 인용문 불일치 원인과 원본 근거 연결 수정 계획

작성일: 2026-09-08. 상태: 구현 전 계획.
연결 작업: R8 운영 요약 hotfix, 086~089의 원본 시간 연결 후속.

## 이번 문서의 범위

사용자가 제공한 운영 로그와 실행 코드 출력으로 확인한 원인 및 후속 구현 계획을 기록한다.
이번 요청에서는 이 문서만 추가한다. 소스 수정, 브랜치 변경, 커밋, push, PR 변경,
운영 배포, 유료 공급자 요청은 실행하지 않는다.
기존 진행 문서와 진행 중인 주 작업의 Git 상태를 변경하지 않는다.

## 확인된 실패와 판단의 한계

운영 출력에서 prompt_version은 `openai-grounded-summary-v3`다.
사용자가 조회한 실행 코드에는 원본 시간 일치 검사 다음에 아래 조건이 있다.

```python
if evidence.quote is not None and evidence.quote not in segment.text:
    raise SummaryValidationError("quote_mismatch", location)
```

| 관측 항목 | 사용자 제공 로그 |
| --- | --- |
| template / phase | other / final_summary |
| 입력 revision | 2 |
| 입력 글자 수 / segment 수 | 1,284 / 22 |
| worker job 시도 | 1 |
| 공급자 시도 1 | 12.640초, quote_mismatch |
| 공급자 시도 2 | 10.696초, quote_mismatch |
| 실패 위치 | 두 응답 모두 key_summary.evidence[0] |
| 최종 결과 | job_failed, SUMMARY_INVALID_OUTPUT |

확정할 수 있는 내용은 다음과 같다.

- 각 응답은 근거 검사에 도달했고 해당 위치에서 인용문 불일치로 거절됐다.
- 실패한 그 근거의 ID는 원본에 존재하고 시간도 일치했다. 두 검사가 인용문 검사보다 먼저다.
- 해당 quote는 null이 아니며 지정 segment의 본문에 연속 문자열로 포함되지 않았다.
- 검사기는 첫 오류에서 중단한다. error_count=1은 전체 잘못된 근거가 하나뿐이라는 뜻이 아니다.
- 두 응답의 실패 위치가 같다고 해서 실제 인용문 값도 같았다고 단정할 수 없다.

아직 확인하지 못한 내용은 다음과 같다.

- 실제 인용문과 지정 원본의 차이: 의역, 내부 띄어쓰기·문장부호 변경, 여러 segment 합성,
  다른 segment 선택 중 무엇인지 확인할 응답 원문이 없다.
- 선택한 근거가 요약 내용을 의미적으로 뒷받침하는지, 뒤쪽 근거가 모두 유효한지.
- 운영 이미지 전체와 API/worker 모든 모듈의 일치 여부. 제공 출력은 조회한 worker 코드의 증거다.

원문을 다시 수집하기 위한 반복 유료 요청은 먼저 하지 않는다.
job/recording 식별자, transcript, quote, 비공개 경로, 키는 이 문서에 기록하지 않는다.

## 분류는 성공하는데 요약이 실패하는 이유

분류의 reason은 자유롭게 작성하는 설명이다. 현재 분류 검증은 필수 필드·자료형,
허용 범주·신뢰도 범위를 확인하며 reason과 원본의 문자열 일치를 요구하지 않는다.
요약은 각 사실의 ID·시간·선택적 quote를 원본과 대조한다. quote가 있으면 원문 부분 문자열이어야 한다.
따라서 분류 설명 생성 성공은 요약의 인용문 복사 계약 충족을 보장하지 않는다.

운영 지시문은 선택적 quote를 붙이라고 하지만 정확한 원문 복사 조건을 명시하지 않는다.
두 번째 요청은 일반적인 교정 지시문과 원래 prompt만 보낸다. 실패한 응답, 오류 종류,
실패 위치를 전달하지 않으므로 무엇을 고쳐야 하는지 구체적으로 알려주는 교정이 아니다.
이는 확인된 구현상의 부족이다. 다만 이번 잘못된 응답의 유일한 생성 원인이라고 단정하지 않는다.

## 수정 결정

**공급자는 요약 내용과 segment ID만 생성하고, 서버가 동일 입력 revision의 원본에서
시간과 근거 문장 전체를 연결한다.**

공급자 evidence 계약은 다음처럼 바꾼다.

```json
{"segment_id":"00000000-0000-0000-0000-000000000001"}
```

최종 저장 Evidence는 기존 필드를 유지한다.

- segment_id: 검증된 원본 UUID.
- start_ms/end_ms: 해당 원본 segment의 시간.
- quote: 해당 원본 segment.text 전체. 모델이 선택한 부분 인용이라는 의미로 표시하지 않는다.

quote를 무조건 null로 저장하는 것도 가능하지만, 이 계획에서는 근거 문장을 보존하기 위해
서버가 원본 전체를 채우기로 한다. 공급자가 인용문을 생성할 책임은 제거한다.
이미 Transcript 검증을 통과한 text를 그대로 사용하며 추가 요약·의역·fuzzy match를 하지 않는다.
기존 NonEmptyText의 정규화가 적용된 transcript를 기준으로 검증한다.

| 대안 | 결정 |
| --- | --- |
| 정확한 복사 지시만 강화 | 오류 확률은 줄일 수 있지만 원본 재생성 책임이 남아 주 해결책으로 선택하지 않는다. |
| quote_mismatch 검사 삭제 | 틀린 인용문을 보존하게 되므로 적용하지 않는다. |
| 실패한 quote만 버리거나 비슷한 문장으로 교체 | 잘못된 공급자 응답을 조용히 통과시키므로 적용하지 않는다. |
| 재시도·timeout 확대 | 확인된 실패 계약을 해결하지 않으므로 유지한다. |
| ID 선택 후 서버에서 원본 연결 | 선택. 시간과 원문 복사 모두 원본 데이터로 결정한다. |

이 방식도 잘못된 segment 선택이나 의미적 환각을 자동으로 검출하지는 못한다.
기존 문자열 일치 검사 역시 의미적 뒷받침을 보장하지 않았다. 의미 품질은 공개 평가와
운영 확인으로 별도 확인하며 이번 수정으로 완전한 의미적 신뢰성을 주장하지 않는다.

## 구현 범위와 계약

1. `summary_references.py`의 EvidenceReference에서 quote를 제거한다.
   StrictModel의 추가 필드 거절을 유지한다. quote:null을 포함해 구계약의 quote,
   start_ms/end_ms를 공급자가 반환하면 schema 오류로 거절한다.
2. 기존 resolve_evidence_references에서 검증된 ID로 같은 호출의 원본을 조회하고
   시간과 quote=segment.text를 함께 넣는다. 알 수 없는 ID는 unknown_segment로 실패한다.
   입력 transcript, 검증된 참조 객체, 공유 어댑터 상태를 변경하지 않는다.
3. `openai_summary.py`의 공급자 schema와 prompt를 ID 전용 출력 계약으로 맞춘다.
   전체 요약·chunk 추출·최종 합성과 다섯 template, 회의 action_items에 모두 적용한다.
4. 최종 CategorySummary/Evidence 및 공통 검증은 유지한다.
   직접 잘못된 최종 quote를 주입하면 quote_mismatch가 계속 발생해야 한다.
   기존 artifact의 유효한 부분 인용 또는 null을 새 정책에 맞춰 일괄 변경하지 않는다.
5. 긴 transcript의 최종 합성 입력은 검증된 fact.text와 ID 중심으로 보낸다.
   서버가 채운 quote·시간을 다시 모델에 반환하도록 요구하지 않으며, 합성 입력의 evidence에서도
   세 필드를 제외한다. 같은 원본 문장을 반복 전송하는 불필요한 context 증가를 피한다.
   최종 단계 input_chars는 실제 전달되는 fact.text 합계로 맞추고 로그 테스트도 수정한다.
   chunk 분할 기준과 원본 입력의 글자 수 정의는 유지한다.
6. 한 원본 segment가 여러 slice에 걸쳐도 원본 segment 전체 시간·본문을 사용한다.
   part_index로 새 시간이나 인용문 구간을 추정하지 않는다. chunk에서 허용되는 ID 검사는 유지한다.
   원본 전체 인용은 제공된 slice 밖 본문도 포함할 수 있으므로 slice 단위 인용이라고 주장하지 않는다.
   최종 요약의 허용 ID 범위는 기존 전체 transcript 기준을 유지한다.

외부 API·OpenAPI·DB·artifact JSON 구조는 유지한다. 외부 schema_version/template_version은
구조가 유지되는 한 올리지 않는다. quote가 원본 전체로 채워지는 의미 변화는 진행 문서와 PR에 명시한다.
긴 segment를 여러 근거가 참조하면 저장 JSON 크기가 증가할 수 있다. 공개 장문 테스트로
생성·조회·렌더링을 확인하며 임의 절단, 별도 중복 제거 시스템, 길이 제한은 섞지 않는다.

## fingerprint와 진단·교정

- prompt_version은 v3에서 v4, provider_schema_version은 2에서 3으로 올린다.
- 시간 전략 `source-segment-time-v1`은 유지하고 원문 연결 전략
  `evidence_quote_strategy=source-segment-text-v1`을 fingerprint에 추가한다.
- 실제 prompt/schema 해시는 새 내용에서 계산한다. API configured fingerprint,
  worker fingerprint, 평가 도구의 고정 기대값을 함께 검증한다.
- 모델·temperature·timeout·job 최대 시도·최초 요청+교정 1회 정책은 유지한다.
- schema/unknown_segment/outside_chunk 진단과 실제 응답 기준 field_path,
  상세 5건 제한·전체/생략 건수·민감 값 비노출을 유지한다.
- 일반 교정 요청이 구체적인 실패 정보를 전달하지 않는 한계는 별도 기록한다.
  이번 수정은 인용문 생성 자체를 제거하는 데 집중하며 교정 대화 재설계는 포함하지 않는다.
  남은 ID/schema 실패가 확인될 경우 안전한 오류 종류·위치 전달을 후속 범위로 검토한다.

## 작업 순서와 PR 계획

후속 구현 착수 시 최신 main과 PR #54 병합 여부를 다시 조회한다. 이번 문서 작성에서
원격 상태를 갱신하거나 기존 PR을 수정하지 않았다.

- #54가 병합됐으면 최신 main에서 `fix/summary-source-quotes`를 만든다.
- #54가 열려 있고 그 변경에 의존하면 `fix/summary-evidence-timestamps`에서 후속 브랜치를
  만들고 PR base도 해당 브랜치로 지정한다. 순서는 #54 → 인용문 수정 PR이다.
- 선행 변경이나 병합 시 저장소 stacked PR 절차대로 후속 base/rebase/check를 정리한다.
- 한국어 PR에 검증·선행/후속 관계·운영 제한을 적고 사용자 요청 없이 병합하지 않는다.

한 인용문 오류를 해결하는 응집된 PR 안에서 다음 단위로 커밋하고 각 단위에 다음 빈 번호의
`docs/progress/NNN_<name>.md`를 추가한다. 번호는 실제 착수 때 확인한다.

| 순서 | 커밋 범위 | 검증 |
| --- | --- | --- |
| 1 | ID 전용 계약·서버 원문 연결·전체/chunk 적용 | schema, adapter, 원본 불변성, 오류 진단 회귀 |
| 2 | fingerprint·평가·합성 입력/로그 정의·API/worker 연결 | 등록·실행·artifact·조회·기존 작업 호환성 |
| 3 | 전체 검사·CI·서버 인계 | 기본 검사, PR base/head, 운영 확인 절차 |

## 필수 회귀와 인수 기준

- 공개 합성 원문과 의역 quote로 기존 quote_mismatch를 재현한다.
- 새 공급자 응답이 ID만 반환해도 최종 quote와 시간이 원본에 정확히 연결된다.
- 다섯 template의 모든 근거 위치·action_items·여러 ID·UUID 표기 차이를 확인한다.
- ID 누락·null·잘못된 UUID·존재하지 않는 ID를 구분해 거절한다.
- quote:null/문자열, 공급자 시간, 임의 추가 필드를 조용히 무시하지 않고 거절한다.
- 빈 facts/evidence·비객체 JSON·범주 불일치·필수 필드/자료형 거절을 유지한다.
- chunk 이탈 ID는 outside_chunk, 직접 잘못된 최종 quote/시간은 기존 오류로 거절한다.
- 분할 segment의 quote/시간은 원본 전체와 같으며, 최종 합성 입력에는 서버 생성 quote/시간이 없다.
- 최초 실패→두 번째 성공, 두 번 실패, 실패 사유 변경 및 안전한 로그 경로를 확인한다.
- 실제 입력 revision에 맞는 API/worker fingerprint, JSON·Markdown·HTTP 조회를 확인한다.
- 기존 완료 artifact 보존, 동일 fingerprint 요청 중복 방지, 다른 fingerprint의 대기 작업과
  기존 stale/UI 상태 제한을 088의 회귀 기준으로 확인한다. 자동 일괄 재요약은 하지 않는다.
- 공개 다섯 범주와 장문 평가에서 기존 필수 사실·담당자/기한 null 기준을 계속 통과한다.
- 원본 transcript/참조 객체 불변성, 공유 어댑터 동시 호출 맥락 분리, 로그·오류의 원문 비노출을 확인한다.

기본 검사: make check-format, make lint, make typecheck, make api-schema-check,
make test-unit, make test-integration, make test-frontend, git diff --check.
기존 .venv로 동등 명령을 실행하면 실제 명령과 결과를 기록한다.
게시 후 최종 head의 GitHub Actions 품질 검사와 Compose/브라우저 smoke를 확인한다.

## 운영 검증과 복구

사용자가 확인한 기존 운영 명령은 다음과 같다.

```bash
docker compose -f compose.yaml -f compose.gpu.yaml up --build -d --wait
```

후속 실행에서도 같은 운영 디렉터리·project·환경 파일·데이터 mount를 유지한다.
위 명령은 환경을 기록한 것으로 이번 계획 작성에서 실행하지 않는다.
구체 배포 커밋과 검증 명령은 구현·CI 완료 후 인계 문서에서 확정한다.

1. 새 유입과 요청을 잠시 멈추고 기존 버전에서 대기/실행 작업을 정상 종료한다.
   088에서 확인한 fingerprint 불일치 작업의 건너뛰기·SUMMARIZING 잔류 위험을 그대로 적용한다.
   진행 불가능한 작업은 원인별로 처리하고 DB fingerprint/revision을 임의 수정하지 않는다.
2. 필요한 허용 필드 로그를 보존한 뒤 API와 worker를 같은 새 버전으로 갱신한다.
   관련 schema/summary_references/openai_summary/summary/평가 모듈 해시와 두 서비스의
   설정 fingerprint를 비교한다. worker만 갱신하지 않는다.
3. 이번 실패 대상의 revision 2가 그대로인지 확인한다. 089의 이전 시간 오류 대상 revision 6과
   혼동하지 않는다. revision이 바뀌었으면 새 입력 검증임을 기록한다.
4. 실제 유료 요청은 별도 운영 단계에서 대상 하나에 수행한다. 새 job ID와 input_revision으로
   최종 검증 성공·job 완료·JSON/Markdown 생성·UI 조회를 확인한다.
5. 서버 내부에서 모든 근거의 ID/시간/quote와 같은 revision 원본의 일치를 확인한다.
   보고에는 검사 건수·불일치 건수·성공 여부만 남긴다. 원문·실제 quote는 출력하지 않는다.
6. 다른 오류가 발생하면 새 사유를 분석하며 같은 유료 요청을 반복하거나 검증을 완화하지 않는다.
7. 복구 시 신규 요청을 멈추고 새 버전의 작업도 정리한 뒤 API·worker를 함께 이전 검증 버전으로
   되돌린다. 기존 데이터와 완료 artifact를 보존하며 다른 fingerprint의 대기 작업을 넘기지 않는다.

실제 NVIDIA/GPU 검증은 불필요하다. 변경 예정 경로는 호스팅 요약 API의 CPU 처리로
GPU 실행·의존성·장치 선택·컨테이너 런타임을 사용하거나 변경하지 않는다.
compose.gpu.yaml은 기존 운영 구성을 유지하기 위한 것이며 GPU 검증 필요성을 뜻하지 않는다.

## 완료 조건과 이번 작성의 검증 범위

구현·공개 회귀·최종 CI와 운영 대상의 실제 성공을 확인하고 관련 PR이 병합된 후
R8 종료 여부를 판단한다. 그전에는 R8 BLOCKED, R9·R10 NOT STARTED를 유지한다.
이번 한 사례의 성공을 과거 모든 요약 실패나 의미적 오류의 해결로 확대하지 않는다.

이번에는 사용자 제공 운영 출력, 로컬 참조 변환·공급자 schema·합성 입력·평가·외부 quote 계약,
089 인계와 저장소 규칙을 읽고 계획 문서를 작성했다. 구현 테스트와 운영 재검증은 향후 항목이다.
