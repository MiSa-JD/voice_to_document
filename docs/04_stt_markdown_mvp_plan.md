# GUI 없는 STT→Markdown 선행 실행 계획

> 상태: 계획 확정
> 목적: R5 화자 검토 GUI를 기다리지 않고, 실제 녹음이 임시 화자 ID를 포함한 Markdown 파일로 쌓이는 경로를 먼저 검증한다.
> 적용 범위: R7-01~R7-04 backend/worker 경로 + 실제 파일 적재 검증

## 1. 결정 사항

- 화자 이름은 당분간 `SPEAKER_00`, `SPEAKER_01` 같은 임시 ID를 그대로 표시한다.
- 사람 이름 매핑, 대표 클립 청취, 화자 수정 GUI는 R5에서 구현한다.
- 이 트랙을 완료해도 로드맵의 R7 M5 전체 완료나 R5 M3 완료로 표시하지 않는다. R7의 정식
  선행조건인 R5 M3와 별개로 진행하는 backend-only 선행 트랙이다.
- 목표 결과는 다음과 같다.

```text
입력 디렉터리의 m4a
  -> stable file detection / job
  -> WhisperX STT + alignment + diarization
  -> transcript JSON
  -> transcript Markdown
  -> 지정된 문서 출력 디렉터리
```

## 2. 범위와 비범위

### 포함

- 허용 범주와 category slug 검증(R7-01)
- transcript 전체와 허용 범주를 받는 구조화 분류 adapter(R7-02)
- 긴 transcript의 context 한도 처리(R7-03)
- 동일 revision의 transcript JSON/Markdown renderer(R7-04)
- worker 성공 경로에서 renderer를 호출하고 지정 출력 디렉터리에 원자적으로 저장하는 연결
- GUI 없이 실행할 수 있는 명령과 fake fixture 기반 재현 검증

### 제외

- `SPEAKER_00`을 실제 인물로 확정하거나 병합하는 기능
- 화자 검토 GUI와 media range API(R5)
- 자동 화자 식별(R6)
- 요약 문서(R8)
- 실제 LLM 공급자와 모델의 최종 선택 전 transcript 외부 전송

## 3. 작업 순서

### P1 — 범주·출력 설정

- `CATEGORIES`, `AUTO_SUMMARY_CATEGORIES`, transcript/document root를 시작 시 검증한다.
- 표시용 범주명과 파일명에 사용할 안전한 slug를 분리한다.
- 출력 root가 입력·cache root와 중첩되지 않는지 확인한다.

### P2 — 구조화 분류 adapter

- 입력은 정규화된 transcript와 허용 범주 목록으로 제한한다.
- 출력 schema는 `category`, `confidence`, `reason`, `schema_version`을 요구한다.
- 알 수 없는 범주, 누락 필드, 깨진 JSON, timeout을 구조화 오류로 변환한다.
- 개인정보 정책이 확정되기 전에는 fake adapter로 동작시키고, 실제 adapter는 명시적 설정에서만
  활성화한다.

### P3 — 긴 transcript 처리

- transcript가 모델 context 한도 안이면 전체 내용을 한 번에 분류한다.
- 한도를 넘을 때만 부분 주제 추출 후 전체 분류를 수행한다.
- 앞부분만 잘라 전체 범주를 결정하지 않는다.
- 분할 과정에서 원본 segment ID, timestamp, 화자 ID를 잃지 않는다.

### P4 — JSON/Markdown renderer

- JSON에는 정밀 timestamp, 원본 segment ID, 임시 화자 ID, 분류 결과와 revision을 보존한다.
- Markdown에는 녹음 메타데이터, 범주, confidence/reason, timestamp, `SPEAKER_XX`를 렌더한다.
- 인접하고 같은 화자인 발화만 읽기 좋게 합치며 JSON 원본은 변경하지 않는다.
- 임시 파일을 같은 파일시스템에 쓴 뒤 `os.replace`로 원자적 rename한다.
- 파일명은 content hash 또는 recording ID 기반으로 만들고 원본 절대 경로를 노출하지 않는다.

### P5 — worker 연결과 CLI 검증

- STT/diarization 성공 후 transcript JSON 저장을 확인하고 Markdown renderer를 호출한다.
- renderer 실패 시 JSON은 남기되 Markdown artifact는 등록하지 않고 job을 명확한 실패 상태로 둔다.
- fake 모드에서 `m4a → JSON → md` 전체 경로를 GUI 없이 반복 실행할 수 있게 한다.
- 실제 모드에서는 기존 R4의 GPU profile과 private input 경로를 사용하고, 출력에는 transcript 본문,
  token, 절대 경로를 기록하지 않는다.

## 4. 산출물과 파일 규칙

- transcript JSON: 기존 schema와 revision을 유지한다.
- transcript Markdown: JSON과 동일한 recording ID/revision을 메타데이터로 포함한다.
- 출력 예시:

```text
<document-root>/2026/08/<recording-id>.md
```

- DB artifact에는 상대 경로와 kind만 저장한다. 실제 절대 경로는 설정 root에서 계산한다.
- 모든 파일 쓰기는 임시 파일 → flush/close → atomic rename 순서를 따른다.

## 5. 완료 기준

다음 조건을 모두 만족할 때 이 선행 트랙을 완료한다.

- GUI를 열지 않고 하나의 명령 또는 worker 감지만으로 m4a를 처리할 수 있다.
- 성공한 녹음마다 transcript JSON과 Markdown이 같은 revision을 가리킨다.
- Markdown에 timestamp와 `SPEAKER_00` 형식의 임시 화자 ID가 표시된다.
- 출력 파일이 지정 document root 밖에 생성되지 않는다.
- 중복 입력 재처리 시 Markdown artifact가 중복 생성되지 않는다.
- 잘못된 분류 응답, timeout, 디스크 쓰기 실패에서 부분 Markdown이 남지 않는다.
- fake unit/integration/E2E와 실제 R4 speech pipeline smoke가 모두 통과한다.
- 공개 로그와 결과 JSON에 transcript 본문, token, 원본 절대 경로가 없다.

## 6. 검증 계획

- Unit: 범주 설정, 분류 schema, context 분할, timestamp/화자 렌더링, slug/path traversal 차단
- Integration: worker 성공·실패 상태, revision 일치, atomic rename, duplicate idempotency
- E2E: 입력 디렉터리 감지 후 목표 document root의 `.md` 생성과 재시작 보존
- 실제 평가: R4 private m4a 중 최소 다중 화자 표본 1개를 사용해 `SPEAKER_XX`와 timestamp를 확인
- 개인정보 점검: 테스트 출력과 progress 문서에 음성 원문·transcript·token을 저장하지 않는다.

## 7. 작업 단위와 재개 지점

- P1~P5는 각각 전용 브랜치와 `docs/progress/NNN_<name>.md` 기록을 가진 독립 작업 단위로
  커밋한다.
- R7-01~04 검증이 끝나면 이 트랙의 결과를 유지한 채 R5-01~04 backend와 R5-05 이후 GUI를
  재개한다.
- R5에서 임시 화자를 실제 인물에 연결하거나 발화를 수정하면 동일 renderer를 다시 호출해
  Markdown 메타데이터를 갱신한다. STT를 불필요하게 재실행하지 않는다.
- R5 완료 전까지는 결과를 “임시 화자 transcript”로 표시하며, 사람이 확정한 이름이 있다고
  가정하지 않는다.

## 8. 중단 기준

- LLM 개인정보 전송 경로가 확정되지 않았는데 실제 transcript를 외부 API로 보내야 하는 경우
  fake adapter와 renderer 검증까지만 진행한다.
- timestamp·revision·path invariant를 확인할 수 없으면 Markdown 생성 성공으로 처리하지 않는다.
- renderer 실패 후 이전 revision의 파일을 새 revision처럼 덮어쓰거나, 부분 파일을 성공 artifact로
  등록하면 작업을 중단하고 원자적 쓰기 계약부터 수정한다.

