# R2-07 — 입력 감지 통합 테스트

- 기록 번호: 017
- 상태: 부분 완료
- 관련 로드맵: R2-07
- 완료 시각: 2026-08-25T05:46:46Z

## 작업한 내용

- scanner, 안정 파일 판정, ffprobe, 스트리밍 SHA-256, recording/job 트랜잭션, job claim을 worker 루프에 연결했다.
- 동일한 파일 버전은 한 번만 scanner 후보로 내보내고 크기나 mtime이 바뀌면 다시 후보가 되도록 했다.
- 손상 입력은 recording으로 등록하지 않고 파일명과 오류 코드만 audit/log에 남기도록 했다.
- 재시도 가능 오류는 최대 3회 지수 backoff, 영구 오류는 즉시 failed로 남기는 R2 handler 경계를 구현했다.
- 임시 디렉터리 기반 integration test로 정상 fixture, 같은 내용의 다른 이름, 손상 입력, scanner 재시작을 검증했다.
- 격리된 `/tmp/voice_to_document_r2.GDQpEf`를 Compose DATA_ROOT로 사용해 합성 fixture 1건의 실제 worker 등록을 확인했다.

## 검증 결과

- `ruff check`: 통과
- 전체 백엔드 `mypy --strict`: 통과
- backend unit 및 discovery integration: 36개 통과
- Compose api/worker/web build 및 healthy 기동: 통과
- Compose worker가 합성 `first.m4a`를 처리한 뒤 임시 DB 상태: recordings 1개, jobs 1개, job status `succeeded`
- Compose 서비스와 전용 network 정상 종료: 통과

## 남은 문제와 결정

- 사용자의 중단 요청에 따라 Compose에서 같은 fixture를 다른 이름으로 추가하는 중복 검증은 실행하지 않았다.
- 사용자의 중단 요청에 따라 Compose worker 재시작 후 DB 상태 유지 검증은 실행하지 않았다.
- 위 두 시나리오는 Python integration test에서는 통과했지만 R2 Compose 데모 증거는 아직 미완료다.
- `/tmp/voice_to_document_r2.GDQpEf`는 삭제하지 않았다. 현재 합성 입력과 테스트용 `app.db`가 남아 있다.
- R2 종료 게이트 체크박스는 수정하지 않았고 R2를 완료 상태로 표시하지 않는다.

## 다음 작업

- 작업을 재개하면 같은 격리 DATA_ROOT에서 동일 fixture의 다른 이름을 추가해 recordings/jobs가 각각 1개인지 확인한다.
- 이어서 worker를 재시작하고 완료 job이 다시 처리되지 않는지 확인한 뒤 R2 전체 회귀와 Compose 종료를 수행한다.
- R2 게이트가 검증된 뒤에만 R3-01 정규화 내부 schema 작업을 시작한다.
