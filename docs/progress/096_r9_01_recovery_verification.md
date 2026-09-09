# R9-01 강제 종료 회귀와 서버 검증 인계

작성일: 2026-09-09. 브랜치: `feature/r9-01-stale-job-recovery → main`.
선행: 095 회수 구현. 후속: R9-02, R9-03 스택. PR 병합은 하지 않는다.

## 실행 결과

기존 .venv를 사용해 Makefile의 uv run 뒤 명령을 직접 실행했다.

| 실제 명령 | 결과 |
| --- | --- |
| `.venv/bin/ruff format --check backend` | 100개 파일 통과 |
| `.venv/bin/ruff check backend` | 통과 |
| `.venv/bin/mypy` | 99개 파일 통과 |
| `.venv/bin/python -m app.openapi --check` | 통과 |
| `.venv/bin/pytest backend/tests/unit backend/tests/integration -q` | 560 통과 |
| `npm --prefix frontend run format:check` | 통과 |
| `npm --prefix frontend run lint` | 통과 |
| `npm --prefix frontend run typecheck` | 통과 |
| `npm --prefix frontend run api:types:check` | 통과 |
| `npm --prefix frontend test` | 33 통과 |
| `.venv/bin/python backend/tests/recovery_probe.py` | SIGKILL 후 같은 ID, attempts 2, 전체 job 4개로 완료 |
| `make compose-smoke` | 격리 Compose, 브라우저 3 통과/실제 공급자 전용 4 제외, 재시작 보존 1 통과, 컨테이너 recovery_probe 통과 |
| `git diff --check` | 통과 |

기존 Starlette/httpx deprecation 경고가 있다. probe는 컨테이너 내부 임시 DB·입력·출력으로
실행하며 운영 데이터를 읽거나 수정하지 않는다. CI도 compose-smoke에서 같은 probe를 실행한다.

## 서버 실제 GPU 검증 (미완료)

사용자가 별도 실행 후 결과를 인계하는 방식이다. 실제 NVIDIA/GPU 통과로 보고하지 않는다.
최초 적용 시 **구버전 worker 종료를 확인한 뒤 신버전 worker를 시작**한다.
구버전은 새 flock에 참여하지 않는다. 최초 운영 적용 전 아래 격리 검증을 먼저 수행한다.

최종 CI 통과 head를 별도 checkout으로 준비하고, 전용 .env.r9-verify를 만든다.
COMPOSE_PROJECT_NAME은 운영과 다른 이름, APP_BIND_HOST=127.0.0.1,
APP_PORT는 사용하지 않는 포트, DATA_ROOT와 RECORDING_INPUT_HOST_DIR,
TRANSCRIPT_HOST_DIR, DOCUMENT_HOST_DIR는 모두 새 빈 검증 디렉터리로 지정한다.
SPEECH_MODE=real, DOCUMENT_MODE=fake로 실제 STT와 화자 경로만 검증한다.
HF_TOKEN은 서버 내부 환경 파일로만 설정하고 출력하거나 커밋하지 않는다.
검증에 사용 허가된 녹음 한 건만 전용 inbox에 복사한다.

```sh
docker compose --env-file .env.r9-verify -f compose.yaml -f compose.gpu.yaml up --build -d
# 전용 UI에서 transcribe running과 실제 음성 처리 시작을 확인한 뒤 실행
docker compose --env-file .env.r9-verify -f compose.yaml -f compose.gpu.yaml kill -s SIGKILL worker
docker compose --env-file .env.r9-verify -f compose.yaml -f compose.gpu.yaml up -d worker
# 로그는 안전한 이벤트 필드만 출력
docker compose --env-file .env.r9-verify -f compose.yaml -f compose.gpu.yaml logs --no-log-prefix worker \
  | jq -R 'fromjson? | select(.event == "job_recovered" or .event == "job_succeeded" or .event == "job_failed") | {event,job_id,recording_id,stage,attempt,action,error_code}'
```

기대: 같은 transcribe job ID가 회수되고 attempts가 증가하며 최종 결과가 생성된다.
긴 정상 작업을 timeout으로 회수하지 않으며 두 번째 worker는 WORKER_ALREADY_RUNNING이다.
전사 JSON 등록 직후 중단한 추가 사례에서는 재시작 전후 전사 결과·segment ID를 서버 내부에서
비교하고 GPU STT 중복 호출 없이 클립·후속 작업만 완료되는지 확인한다.
통합 fake probe는 이 경계를 결정적으로 검사하지만 실제 GPU 경계 검증을 대신하지 않는다.

실제 GPU 실패 후 수동 재시도는 R9-02 head에서 전용 UI의 실패 작업으로 실행한다.
원 실패 job은 failed로 유지되고 새 job attempts가 1부터 시작하는지 확인한다.
STT 재수행 실패는 기존 전용 폼으로 새 힌트를 입력하며 삭제된 힌트를 복원하지 않는다.
화자 embedding 모델 접근이 막히면 해당 코드와 접근 승인 미완료만 분리해 기록한다.
R6의 접근 승인·평가 표본 blocker를 이번 검증 성공으로 해제하지 않는다.
GPU runtime 자체를 바꾸지 않아 성능 평가·batch size 탐색은 반복하지 않는다.

검증 결과에는 안전한 ID·상태·attempts·중복 건수·오류 코드만 남긴다.
원문·원본 경로·credential·원시 예외는 공유하지 않는다. 종료는 동일 환경 파일·project로 한다.

```sh
docker compose --env-file .env.r9-verify -f compose.yaml -f compose.gpu.yaml down --remove-orphans
```

검증 데이터는 결과 검토까지 보존한다. 서버 결과 수신 후 실패 항목 수정 및 PR 검증 상태를 갱신한다.
