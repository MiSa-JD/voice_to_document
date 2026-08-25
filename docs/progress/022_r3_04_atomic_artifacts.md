# R3-04 — 원자적 artifact와 fake pipeline 연결

- 기록 번호: 022
- 상태: 완료
- 관련 로드맵: R3-04
- 완료 시각: 2026-08-25T06:08:16Z

## 작업한 내용

- 최종 파일과 같은 디렉터리에 임시 파일을 쓰고 flush, fsync, `os.replace`로 교체하는 artifact writer를 구현했다.
- artifact의 SHA-256, schema version, revision, 상대 경로를 DB에 멱등하게 등록하도록 했다.
- transcript JSON/Markdown과 category별 summary JSON/Markdown 경로 및 renderer를 구현했다.
- category를 안전한 Unicode 경로 조각으로 변환하고 경로 구분자, `..`, 제어 문자를 거부하도록 했다.
- fake transcribe, classify, summarize handler를 worker 기본 fake 경로에 연결했다.
- transcribe 결과를 segments와 transcript JSON에 저장하고, 검토 필요 fixture는 SPEAKER_REVIEW에서 멈추도록 했다.
- 완료 fixture는 classify와 자동 summarize job을 순서대로 등록해 COMPLETED까지 진행하도록 했다.
- real AI worker는 실제 구현 전 성공으로 위장하지 않고 R4 이전에는 시작을 거부하도록 했다.

## 검증 결과

- Ruff: 통과
- mypy strict: 통과
- artifact, fake pipeline, worker 관련 테스트: 11개 통과
- 완료 fixture: transcribe/classify/summarize job 각 1개 succeeded, recording COMPLETED
- 완료 fixture artifact: transcript JSON/Markdown, summary JSON/Markdown 각 1개
- review fixture: SPEAKER_REVIEW, transcribe job만 존재
- 동일 artifact 재작성: DB 행 1개와 최종 파일 1개 유지
- 파일 쓰기 실패: 최종 파일, 임시 파일, DB 행 없음
- DB 등록 실패: 완성 파일 보존 후 재시도로 DB 등록 복구

## 남은 문제와 결정

- R3에서는 Markdown을 단순하고 재생성 가능한 표현물로 유지하며 복잡한 템플릿 엔진을 추가하지 않았다.
- 범주 변경과 화자 수정에 따른 artifact 무효화는 해당 쓰기 API가 도입되는 R5 이후에 확장한다.

## 다음 작업

- R3-05에서 녹음 목록과 상세 API, 공통 오류 응답을 구현한다.
