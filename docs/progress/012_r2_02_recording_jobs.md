# R2-02 — recording/job 저장 연산

- 기록 번호: 012
- 상태: 완료
- 관련 로드맵: R2-02
- 완료 시각: 2026-08-25T05:33:23Z

## 작업한 내용

- recording과 최초 transcribe job을 하나의 `BEGIN IMMEDIATE` 트랜잭션으로 등록하는 저장 연산을 구현했다.
- 신규 recording과 job에 UUID를 사용하고 원본 이름, 현재 source path, 콘텐츠 해시, 크기, 길이, UTC 시각을 저장하도록 했다.
- 같은 콘텐츠 해시가 이미 있으면 원래 recording ID를 반환하고 source path만 갱신하며 새 job은 만들지 않도록 했다.
- 동시 최초 접근에서도 migration과 등록이 안전하도록 migration 자체도 `BEGIN IMMEDIATE`로 직렬화했다.

## 검증 결과

- `ruff check`: 통과
- 전체 백엔드 `mypy --strict`: 통과
- recording과 job 동시 생성: 통과
- 같은 해시를 두 thread에서 동시에 등록해 recording/job 각 1개 유지: 통과
- job insert 강제 실패 시 recording까지 rollback: 통과
- migration 및 repository 관련 테스트 7개 통과

## 남은 문제와 결정

- 같은 해시의 추가 경로 이력 테이블은 현재 요구에 필요하지 않아 만들지 않고 최신 source path와 최초 original name만 보존한다.
- 실제 hash와 ffprobe metadata 계산은 R2-04/R2-05에서 연결한다.

## 다음 작업

- R2-03에서 재귀 m4a 검색, 임시 파일·symlink 제외, 크기/mtime 안정 판정을 구현한다.
