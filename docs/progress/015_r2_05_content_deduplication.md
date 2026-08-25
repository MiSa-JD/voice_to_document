# R2-05 — 스트리밍 SHA-256 중복 방지

- 기록 번호: 015
- 상태: 완료
- 관련 로드맵: R2-05
- 완료 시각: 2026-08-25T05:36:34Z

## 작업한 내용

- 파일 전체를 메모리에 올리지 않고 기본 1MiB chunk로 읽는 SHA-256 계산을 구현했다.
- 안정 파일의 stat, ffprobe, SHA-256, 재확인 stat, recording 등록을 잇는 ingest 함수를 구현했다.
- 검사 중 크기나 mtime이 바뀌면 등록하지 않고 `FileChangedDuringIngestError`로 다음 scan을 기다리게 했다.
- 같은 콘텐츠의 다른 이름은 기존 recording에 연결하고 새 job을 만들지 않도록 R2-02 저장 연산과 연결했다.
- 같은 경로의 콘텐츠가 달라지면 새 콘텐츠 해시와 recording/job으로 처리하도록 했다.

## 검증 결과

- `ruff check`: 통과
- 전체 백엔드 `mypy --strict`: 통과
- 약 2.4MB 파일을 4KiB chunk로 계산한 SHA-256과 표준 기대 해시 일치
- 같은 콘텐츠·다른 이름: recording/job 각 1개
- 최초 original name 보존 및 최신 source path 갱신
- 같은 경로·다른 유효 m4a: recording/job 각 2개
- ingest 단위 테스트 3개 통과

## 남은 문제와 결정

- stat 사이에 동일 크기와 동일 mtime으로 파일을 교체하는 비정상적인 외부 동작은 별도 file descriptor lock 없이 완전히 탐지할 수 없다. 정상 Syncthing 복사 흐름에는 크기/mtime 안정화와 콘텐츠 해시가 충분한 최소 안전선이다.
- source path별 전체 관찰 이력 테이블은 현재 범위에서 추가하지 않는다.

## 다음 작업

- R2-06에서 queued job의 원자적 claim, 성공/실패 이력, SIGTERM 시 반환을 구현한다.
