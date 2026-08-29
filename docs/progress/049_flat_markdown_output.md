# Flat Markdown 출력 경로

- 분류된 schema v2 JSON을 기존 transcript UUID 경로에 먼저 원자적으로 저장한다.
- 최초 렌더 직전에 고정한 document identity로 Markdown을 document root의 단일 파일에 저장한다.
- Markdown artifact의 `relative_path`에는 `{sequence:04d}_{title}.md` 파일명만 기록한다.
- Compose의 API는 document mount를 read-only, worker는 read-write로 유지하면서 `DOCUMENT_HOST_DIR` override를 추가했다.
- `.env.example`과 README에 기본 경로, 공백 경로의 작은따옴표 표기, 새 출력 구조를 문서화했다.
