# R7-04 transcript JSON·Markdown renderer

## 상태

- backend-only 선행 트랙의 P4 완료

## 변경

- schema v2 JSON에 recording ID, content hash, revision, millisecond 시간, segment ID, 임시 화자
  ID 및 schema v1 분류 결과를 보존한다.
- Markdown에 recording ID/revision, category, confidence/reason, millisecond timestamp와
  `SPEAKER_XX`를 표시한다.
- 바로 인접한 동일 assigned speaker 발화만 Markdown view에서 병합한다. 원본 JSON segment는
  변경하지 않으며 미배정 발화끼리는 병합하지 않는다.
- canonical recording UUID 기반 상대 경로만 생성한다.
- artifact 저장은 같은 디렉터리의 임시 파일을 flush/fsync한 뒤 `os.replace`하고 디렉터리까지
  fsync한다.

## 검증

- JSON 보존, Markdown 병합, millisecond timestamp, 미분류 거부, 상대 경로 차단 unit test
- 부분 임시 파일 및 root 탈출을 막는 기존 atomic artifact test 유지
- transcript 본문, token, 입력 절대 경로를 이 문서에 기록하지 않음
