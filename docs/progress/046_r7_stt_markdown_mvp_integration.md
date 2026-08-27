# R7 STT→Markdown MVP worker 통합

## 상태

- backend-only 선행 트랙 P5 완료
- R7-01~04의 선행 경로만 구현했으며 R5, R6 및 R7 M5 전체는 완료 처리하지 않음

## 연결

- worker의 `m4a → STT → alignment → diarization → transcript JSON → fake 분류 → Markdown`
  경로를 연결했다.
- 화자 검토가 필요한 transcript도 `needs_speaker_review`를 유지한 채 임시 `SPEAKER_XX`로
  Markdown을 생성한다.
- 실제 공급자는 사용하지 않으며 committed fixture fake adapter만 호출한다.
- 분류 완료 시 schema v2 JSON을 같은 revision으로 갱신한 뒤 document root에 schema v1 Markdown을
  원자적으로 저장한다.
- summary job은 이 선행 트랙에서 enqueue하지 않는다.

## 실패·멱등성

- Markdown renderer 실패 시 분류가 포함된 JSON은 보존하고 Markdown artifact를 등록하지 않으며
  recording/job을 명시적으로 실패 처리한다.
- content hash 중복 입력과 handler 재생성 뒤에도 revision별 JSON/Markdown artifact는 각각 하나다.
- DB에는 설정 root 기준 상대 경로, kind, schema version, revision을 저장한다.

## 검증

- `make check-format`, `make lint`, `make typecheck`, `make api-schema-check` 통과
- `make test`: unit 243개, frontend 9개, integration 11개 통과
- `make test-stt-markdown-e2e`: 파일 감지→artifact 생성→restart 보존 test 1개 통과
- `make compose-smoke`: Docker build/health, browser pipeline 2개, worker restart 보존 1개 통과
- `make test-e2e`의 Playwright 3개는 compose smoke에서 worker restart 전후로 나누어 모두 실행했다.
- fake fixture 완주, 임시 화자 Markdown, revision 일치, renderer 실패, 중복/restart integration test
  통과
- stub speech adapter를 사용한 real-speech worker 연결 unit test 통과
- Linux host의 NVIDIA GeForce RTX 3060 12GB와 Docker `nvidia` runtime을 확인했다.
- private 다중 화자 m4a 1개를 real WhisperX STT·alignment·pyannote diarization과 local fake
  분류로 처리했다. revision 1에서 segment 144개와 임시 화자 2명을 확인했고 JSON/Markdown의
  timestamp, `SPEAKER_XX`, 동일 revision 검증을 통과했다.
- private content hash가 committed fixture에 없을 때도 외부 전송 없이 마지막 허용 범주와 고정 근거를
  사용하는 deterministic fallback으로 Markdown까지 완주한다.
- transcript 본문, token, 원본 절대 경로를 로그나 이 문서에 기록하지 않음
