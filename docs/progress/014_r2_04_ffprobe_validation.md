# R2-04 — ffprobe 입력 검사

- 기록 번호: 014
- 상태: 완료
- 관련 로드맵: R2-04
- 완료 시각: 2026-08-25T05:35:44Z

## 작업한 내용

- shell 문자열 없이 ffprobe 인자 배열을 실행하는 media probe를 구현했다.
- audio stream, 양수 duration, codec, 선택적 creation time을 정규화된 `MediaInfo`로 반환하도록 했다.
- 실행 파일 없음, timeout, 손상 container, 잘못된 JSON, audio 없음, 잘못된 duration 오류 코드를 구분했다.
- 사용자용 오류 메시지에서 입력 파일의 전체 경로를 노출하지 않도록 했다.

## 검증 결과

- `ruff check`: 통과
- 전체 백엔드 `mypy --strict`: 통과
- 공백과 한글이 있는 경로의 AAC fixture: 2000ms로 정상 판정
- 손상 fixture: `MEDIA_CORRUPT`
- ffprobe 실행 파일 없음: `FFPROBE_NOT_FOUND`
- subprocess timeout: `FFPROBE_TIMEOUT`
- media probe 단위 테스트 4개 통과

## 남은 문제와 결정

- ffprobe stderr의 원문은 사용자 오류에 포함하지 않는다. R9 운영 진단이 필요하면 비민감한 요약만 구조화 로그에 추가한다.
- 실제 원본 metadata의 recorded_at 우선순위는 R7 문서 렌더 단계에서 확정한다.

## 다음 작업

- R2-05에서 chunk 기반 SHA-256과 scanner→probe→중복 등록 흐름을 연결한다.
