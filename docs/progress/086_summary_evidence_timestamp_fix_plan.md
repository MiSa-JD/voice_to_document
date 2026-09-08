# 요약 근거 시간 오류의 원인과 수정 계획

작성일: 2026-09-08. 상태: 구현 전 계획.

## 결론과 확실성의 범위

**이번에 제공된 실패 요청의 직접 원인은 요약 응답에 포함된 근거의
`end_ms <= start_ms` 시간 범위 오류로 판단할 수 있다.**
현재 코드에서 `evidence[숫자]` 객체 위치의 Pydantic `value_error`를 발생시키는
검사는 `Evidence.validate_time_range`의 이 조건이다.
시간이 같은 경우와 역전된 경우 모두 공개 합성 값으로 같은 오류 유형을 재현했다.

단, 아래 세 가지는 구분한다.

- 확인: 최초 응답과 교정 응답 모두 근거 객체의 시간 범위 검사에서 실패했다.
- 코드에 근거한 판단: 원본 transcript는 요약 요청 전에 Segment 시간 범위 검증을
  통과하므로 모델이 원본 시간을 응답에 다시 작성하는 단계가 문제 발생 지점이다.
- 미확인: 실제 잘못된 시간 값, 동일 시간인지 역전인지, 모델이 그렇게 생성한 이유,
  시간 문제를 제거한 이후의 ID·quote 검증 결과, 과거 다른 요청도 같은 원인인지.

운영 worker의 openai_summary 모듈 SHA-256은 다음과 같으며 확인한 로컬 코드와 일치했다.
`094d06392dca43581dba88c0758a0e032751ff2144afbd13ca898baf07ab4f05`
이는 해당 모듈의 일치 증거이며 컨테이너 전체와 schema 모듈까지 동일하다는 증명은 아니다.
구현 후 운영 재검증에서는 관련 모듈 전체의 배포 일치를 확인한다.

**모든 summary 실패의 해결이 보장됐다는 의미는 아니다.**
이번 수정의 성공 기준은 확인된 시간 생성 오류를 구조적으로 제거하면서
ID·인용문·범주별 내용 검증을 유지하는 것이다.

## 운영 증거 — 식별자와 원문은 제외

| 항목 | 확인된 값 |
| --- | --- |
| 실제 입력 revision | 6 |
| template / phase | lecture / final_summary |
| 본문 글자 수 / segment 수 | 4,010 / 155 |
| job 시도 | 1 |
| provider 시도 1 | 45.942초, schema 오류 4건 |
| provider 시도 2 | 29.848초, schema 오류 5건 |
| 오류 유형 | 모두 value_error |
| 오류 위치 | core_topics, concepts, examples, review_items의 evidence 객체 |
| 최종 코드 | SUMMARY_INVALID_OUTPUT |

두 응답 모두 생략된 오류는 0건이다. chunk 추출이나 timeout 실패는 이 요청의 직접 원인이 아니다.
현재 schema 검사가 먼저 실패했으므로 후속 evidence 검증이 통과했다고 해석하지 않는다.
운영 job ID, transcript, 응답 원문, 인용문, 실제 시간 값, 키, 비공개 경로는 기록하지 않는다.

## 수정 결정과 대안

**모델은 segment ID와 선택적 quote를 반환하고, 서버가 같은 입력 revision의 원본
segment에서 start_ms/end_ms를 채운다.**

현재는 이미 원본에 정해진 시간 숫자를 모델에게 다시 생성하게 한다.
공급자 JSON schema는 각 숫자의 자료형·최솟값을 정하지만 원본 시간과의 일치까지 보장하지 않는다.
모델에게 정답 숫자를 반복 작성시키는 책임을 제거하는 것이 이번 수정의 핵심이다.

| 대안 | 판단 |
| --- | --- |
| 시간 복사 프롬프트만 강화 | 생성 오류 재발 가능성이 남아 주 해결책으로 선택하지 않는다. |
| timeout·재시도·교정 횟수 확대 | 확인된 오류 원인을 제거하지 않으며 비용과 대기만 늘 수 있다. |
| 잘못된 시간 허용, 근거 삭제, 시간 임의 보정 | 근거 검증을 약화시키므로 적용하지 않는다. |
| 모델이 낸 시간을 무조건 덮어쓰기 | 과도기 우회 대신 공급자 계약에서 시간 반환 책임을 명확히 제거한다. |
| 서버가 원본 시간 부여 | 선택. 원본 데이터로 결정 가능한 값을 서버가 책임진다. |

## 내부 공급자 계약과 최종 저장 계약

공급자 응답의 evidence는 다음처럼 단순화한다. 예시는 공개 합성 ID다.

```json
{"segment_id":"00000000-0000-0000-0000-000000000001","quote":null}
```

최종 CategorySummary/Evidence에는 기존처럼 segment_id/start_ms/end_ms/quote를 저장한다.
외부 HTTP API, OpenAPI, artifact JSON·Markdown, DB schema와 renderer 계약은 유지한다.
현재 `Evidence.validate_time_range` 및 원본과 정확히 일치해야 하는 최종 검증도 유지한다.

처리 순서는 다음과 같다.

1. 공급자 JSON을 해석한다. 범주별 구조와 사실 목록의 필수 필드·자료형·추가 필드 규칙을 유지한다.
2. 알려진 범주 필드 안의 evidence 위치에서만 ID·quote 참조 구조를 검사한다.
   작은 StrictModel 등 기존 Pydantic 방식을 재사용하고 별도 범용 변환 프레임워크는 만들지 않는다.
   전체 JSON에서 이름이 evidence인 임의 키를 찾아 변환하거나 잘못된 노드를 버리지 않는다.
3. 검증된 UUID로 이 호출에 사용한 transcript의 segment를 조회한다.
   UUID 표현이 달라도 동일 UUID로 비교한다. 자료형 오류와 존재하지 않는 ID를 구분한다.
4. 원본 segment의 시간을 넣어 기존 모델로 검증한다. 누락되거나 잘못된 ID에 시간을 추정하지 않는다.
5. 기존 공통 evidence 검증으로 시간 일치, quote 포함 여부와 chunk 소속을 확인한다.
6. 검증된 결과만 반환·저장한다. 입력 transcript와 공유 어댑터 상태를 변경하지 않는다.

새 참조 계약에 없는 공급자 start_ms/end_ms나 다른 추가 필드는 조용히 무시하지 않고 거절한다.
최종 schema 버전과 공급자 응답 형식의 버전은 구분한다.

## 전체 요약과 chunk 경로

전체 요약, chunk 사실 추출, 추출 사실을 모은 최종 요약에 동일한 ID→원본 시간 변환을 적용한다.
회의 action_items의 evidence도 포함해 다섯 template의 모든 근거 위치를 점검한다.

- chunk 추출에서는 제공한 chunk에 없는 segment 참조를 기존 outside_chunk로 거절한다.
- 하나의 원본 segment를 여러 slice로 나눈 경우에도 시간은 해당 원본 segment 전체 구간이다.
  part_index로 새로운 시간을 만들거나 slice 글자 수로 시간을 추정하지 않는다.
- 최종 요청 자료의 추출 사실도 ID·quote 중심의 공급자 표현으로 통일한다.
  내부에서 이미 검증된 시간 값을 모델이 다시 반환하게 만들지 않는다.
- quote는 기존과 동일하게 원본 segment 본문 포함 여부로 검증한다.
  이번 수정에서 slice 본문만으로 제한하는 별도 정책 변경을 섞지 않는다.
- 최종 요약의 허용 segment 범위도 기존 전체 transcript 기준을 유지한다.
- 중복 근거 제거, 사실 합치기, 의미적 충실성 판정 같은 별도 변경은 포함하지 않는다.

## 로그·오류·fingerprint

083~085에서 추가한 요청별 진단과 실행 맥락 계약을 유지한다.
새 참조 검증 오류도 실제 응답 기준 field_path를 기록하고 알 수 없는 키·유형을 대체한다.
상세 5건 제한, 전체·생략 건수, 원문·값·예외·traceback 비노출을 유지한다.
없는 ID는 unknown_segment, 잘못된 quote는 quote_mismatch, chunk 이탈은 outside_chunk로 구분한다.
JSON·schema·evidence 실패에 대한 최초 요청+교정 1회와 최종 외부 오류 코드는 유지한다.

**이번에는 진단만 추가한 PR과 달리 fingerprint를 의도적으로 변경해야 한다.**
공급자 schema와 prompt가 바뀌므로 관련 해시와 prompt_version을 갱신하고,
서버의 시간 부여 방식을 나타내는 고정 전략 버전을 fingerprint에 포함한다.
출력 artifact schema_version/template_version은 실제 외부 구조가 유지되면 올리지 않는다.
평가 도구의 고정 기대값과 API의 configured fingerprint도 함께 맞춘다.
모델명, temperature, timeout, job 최대 시도 수, 교정 횟수와 chunk 분할 기준은 유지한다.

API는 작업 등록 시 fingerprint를 계산하고 worker는 실행 시 이를 비교한다.
따라서 worker만 새 코드로 갱신하면 이전 API가 등록한 작업과 계약이 어긋날 수 있다.
API·worker를 같은 릴리스로 갱신하며, 기존 완료 artifact는 보존하고 일괄 재요약하지 않는다.
구버전 fingerprint의 대기 작업이 신규 worker에서 조용히 완료 처리될 위험과
현재 중복 등록·stale 표시 동작을 구현 단계의 통합 테스트로 확인한다.
배포 전에 기존 요약 대기·실행 작업을 정상 종료시키는 운영 절차를 기본으로 하고,
남은 작업을 임의 DB 수정으로 신버전 fingerprint에 맞추지 않는다.

## 구현 순서와 검증 경계

이번 문서 작성에서는 문서 한 개만 추가한다. 코드 구현·커밋·push·PR 게시·배포는 실행하지 않는다.
후속 구현은 최신 main 및 진단 PR의 병합 상태를 다시 확인한 뒤 시작한다.
독립 hotfix 예정 관계는 `fix/summary-evidence-source-timestamps → main`이다.
진단 코드가 main에 없으면 의존 관계를 먼저 명시하고 base 계획을 조정한다.
PR 제목·본문·검증·관계는 한국어로 작성하고 요청 없이 병합하지 않는다.

| 순서 | 구현 및 커밋 경계 | 검증 |
| --- | --- | --- |
| 1 | 공개 시간 오류 재현, ID 참조 계약·원본 시간 변환, 전체/chunk 적용 | schema·근거·범주별 adapter 회귀 |
| 2 | fingerprint·평가·로그 및 API/worker 계약 연결 | job 등록·실행·artifact·오류·맥락 통합 회귀 |
| 3 | 전체 검사, 서버 갱신·검증·복구 인계 문서 | 기본 검사, CI, base/head 확인 |

각 단계는 목적·변경·실행 검증·제한·GPU 필요 여부를 새 진행 문서에 기록한다.
번호는 착수 시 다음 빈 번호를 사용하며 기존 계획과 기록을 덮어쓰지 않는다.

## 필수 회귀 테스트

| 검증 항목 | 기대 결과 |
| --- | --- |
| 공개 시간 오류 재현 | 기존 Evidence에 동일/역전 시간 입력 시 이번과 같은 value_error 발생 |
| 시간 없는 정상 참조 | 전체/chunk/최종 병합 모두 원본 시간을 정확히 채워 최종 검증 통과 |
| 여러 segment·다섯 template·action_items | 올바른 위치와 해당 ID의 시간이 연결됨 |
| 하나의 segment가 여러 chunk로 분할됨 | slice 계산 없이 원본 시간 유지, 기존 quote 정책 유지 |
| ID 누락·잘못된 UUID·null·알 수 없는 필드 | schema 실패, 필드·유형 안전하게 기록 |
| 존재하지 않는 ID | unknown_segment, 시간 추정·근거 삭제 없이 실패 |
| 원문에 없는 quote / chunk 밖 ID | quote_mismatch / outside_chunk 유지 |
| 공급자가 시간 필드를 반환 | 새 참조 계약의 추가 필드 오류로 거절 |
| 빈 facts·빈 evidence·비객체 JSON | 기존 거절 정책 유지 |
| 최초 실패→교정 성공, 두 번 실패, 사유 변경 | 요청 횟수·진단 순서·최종 오류 코드 유지 |
| 최종 Evidence의 직접 잘못된 시간 | 시간 범위와 원본 일치 검사가 여전히 거절 |
| 저장 JSON·Markdown/API | 원본 근거 시간 포함, 기존 외부 계약 유지 |
| 동일 revision의 API/worker fingerprint | 등록과 실행 일치, 새로운 의미 변경 반영 |
| 구버전 fingerprint·기존 완료 artifact | 기존 작업/결과 처리 영향 확인, 자동 일괄 재요약 없음 |
| 민감 문자열·동시 호출 | formatter·저장 오류 메시지에 누출 없음, 맥락 혼합 없음 |

저장소 기본 검사: make check-format, make lint, make typecheck, make api-schema-check,
make test-unit, make test-integration, make test-frontend, git diff --check.
기존 .venv로 동등 명령을 실행하면 실제 실행 방식을 기록한다.
PR 게시 후 GitHub Actions의 품질 검사 및 Compose/브라우저 smoke도 확인한다.

## 운영 재검증과 완료 조건

운영 배포와 유료 재요청은 후속 별도 단계다. 같은 입력의 반복 유료 요청으로 원인을 더 찾는
대신 먼저 공개 회귀 테스트와 구현을 완료한다.

1. 검증 커밋·CI·배포 대상과 API/worker 동일 fingerprint를 확인한다.
   관련 schema/summary/openai_summary/pipeline 모듈의 실행 파일 해시도 확인한다.
2. 기존 운영 project·환경 파일·데이터 mount를 보존한다.
   재생성 전에 필요한 로그를 확보하고 기존 요약 작업의 대기·실행 상태를 정리한다.
3. API와 worker를 같은 버전으로 갱신한다. 복구 시에도 둘을 같은 이전 버전으로 되돌린다.
   구체 명령은 구현 당시 운영 구성에 맞춘 후속 인계 문서에 작성한다.
4. 원래 실패한 revision 6이 여전히 재현 가능한지 확인한다.
   현재 revision이 달라졌다면 새 입력 검증임을 명시하며 DB revision을 되돌리지 않는다.
5. 대상 하나를 수동 요청해 새 job ID·실제 입력 revision으로 085의 허용 필드 로그를 수집한다.
6. 최종 요약 검증 성공, job 완료, JSON/Markdown artifact 생성과 UI 조회를 확인한다.
   원본과 근거 시간의 일치는 서버에서 비교하고 원문 대신 통과 여부·불일치 건수만 보고한다.
7. 다른 오류가 나타나면 그 사유를 별도로 분석한다. 검증을 완화하거나 근거를 버려 통과시키지 않는다.

완료 기준은 코드/회귀/CI 통과와 운영 대상의 실제 성공 및 관련 수정 PR 병합이다.
그 전까지 R8은 BLOCKED, R9·R10은 NOT STARTED를 유지한다.
이번 한 요청의 성공을 과거 모든 schema/evidence 실패가 해결됐다는 증거로 확대하지 않는다.

## GPU 및 이번 문서 작성 검증

계획한 변경은 호스팅 요약 API의 CPU 경로에 한정된다.
GPU 실행, CUDA/NVIDIA 의존성, 장치 선택, GPU 컨테이너 런타임을 바꾸지 않으므로
실제 NVIDIA/GPU 검증은 불필요하다.

문서 작성 시 현재 schema, 요약 어댑터, transcript 로더, fingerprint 계산과 평가 경로를 읽었다.
공개 UUID와 합성 시간으로 동일/역전 시간의 Evidence value_error를 메모리에서 재현했다.
운영 데이터 조회·변경이나 공급자 호출은 실행하지 않았다.
전체 구현 검사는 향후 실행 항목이며 이 문서 작성에서 통과했다고 보고하지 않는다.
