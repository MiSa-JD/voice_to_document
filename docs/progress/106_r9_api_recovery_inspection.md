# R9 API 복구 검사 분리 — 상세 조회 500 수정

작성일: 2026-09-12. 상태: **VERIFY — 로컬 검증 통과, 새 커밋의 서버 실제 GPU 검증 대기**.
브랜치: `fix/r9-api-recovery-inspection` → `main`.
선행: #56~#59 모두 2026-09-10 병합, 기준 main `00f782b`.
원인과 운영 표본: [105 계획](105_r9_detail_500_fix_plan.md).
기존 서버 결과: [104 GPU 검증 기록](104_r9_server_gpu_verification.md).

## 원인과 변경

실패 이력이 있는 상세 GET과 수동 재시도 POST는 `recovery_handler()`를 공유한다.
기존 구현은 worker의 실제 음성 처리기를 생성했고, API에 마운트하지 않은 모델 캐시를
`WhisperXConfig`가 검사하면서 500을 발생시켰다. 현재 완료된 녹음도 과거 실패 이력이
하나라도 있으면 영향을 받았다.

- `document_adapters.build_document_adapters()`에 worker의 기존 문서 어댑터 구성만 옮겼다.
  real 모드의 OpenAI 분류·장문 분류·요약 설정을 그대로 전달하고, fake 모드는 기존
  `FakePipelineHandler`의 기본 어댑터 선택에 맡긴다.
- API는 문서 어댑터와 `FakePipelineHandler`를 검사 목적으로만 구성한다. worker나
  실제 음성 처리기를 import·생성하지 않는다. 원래 speech/document 모드는 유지하며,
  API 검사 객체의 공급자 키만 기존처럼 빈 값으로 처리한다.
- worker는 공통 함수를 호출한 후 기존 real/fake 음성 처리기를 선택한다. credential,
  모델, context 제한, timeout 및 fingerprint 의미를 유지한다.
- 공개 API·OpenAPI·DB schema와 복구 판단 규칙은 변경하지 않았다. revision, artifact,
  입력 검사, 재시도 중복 방지, 요약·재전사 전용 요청 정책은 기존 검사를 함께 통과했다.
  API에 모델 캐시·GPU·공급자 키를 추가하지 않았다.

## 재현과 회귀 결과

수정 전 합성 녹음으로 캐시 없음·파일·권한 없음 × 실패 상태·완료 상태 6개 사례가
음성 설정 검사에서 실패하는 것을 재현했다. 수정 후에는 실제 완료 artifact를 갖춘
녹음까지 상세 GET 200과 실패 이력 보존을 확인했다.

새 회귀 검사는 다음을 보장한다.

- real/real, HF·LLM 키 없음, 사용할 수 없는 캐시에서도 상세 조회와 POST 202 성공.
- 동시 요청 2개와 반복 요청이 재시도 job 하나를 재사용하며 원 실패 job 보존.
- revision 변경, 활성 작업, 입력 누락, fingerprint 변경은 복구 불가 및 POST 409 유지.
- API 검사 중 worker 빌더·실제 음성 생성자·모델 로더·외부 HTTP 호출 시 즉시 실패하는 감시.
- 별도 Python 프로세스에서 API 복구 모듈 import가 worker·음성 실행 모듈을 import하지 않음.
- worker의 네 가지 모드 조합, 설정·키 전달, API/worker 분류·요약·화자 설정 fingerprint 일치.

`compose-smoke.sh`는 기존 fake E2E를 끝낸 뒤 worker를 중지하고 API만 real/real로 재생성한다.
합성 DB/artifact를 재사용하며, 새 사례에서 worker가 실행 중이지 않은지 명시적으로 검사한다.
API에 `/models`와 키가 없는지 확인하고, 브라우저에서 완료 결과·실패 이력 표시,
재시도 등록·반복 POST 202, 새 job queued 및 원 job failed 보존을 확인했다.
공급자 주소는 루프백의 닫힌 포트이며 실제 공급자를 사용하지 않는다.

## 실행한 검사

로컬 PATH에 uv 실행 파일이 없어 Makefile의 Python 검사와 같은 `.venv/bin` 명령을 직접 실행했다.
Compose의 포트 바인딩·Docker 소켓은 sandbox에서 거부되어 승인된 sandbox 밖 실행으로 재검사했다.
이를 GPU 접근 실패로 해석하지 않는다.

| 검사 | 결과 |
| --- | --- |
| `.venv/bin/ruff format --check backend` | 105개 파일 통과 |
| `.venv/bin/ruff check backend` | 통과 |
| `.venv/bin/mypy` | 104개 파일 통과 |
| `.venv/bin/python -m app.openapi --check` | 통과 |
| `.venv/bin/pytest backend/tests/unit backend/tests/integration -q` | 611개 통과 |
| 프런트엔드 `format:check`, `lint`, `typecheck`, `api:types:check` | 각각 통과 |
| `npm --prefix frontend test` | 36개 통과 |
| `make compose-smoke` | 기본 브라우저 3개, 재시작 보존 1개, fake 재시도 1개, real/real 복구 1개 통과 |
| Compose 내부 `recovery_probe.py` | SIGKILL/restart, job 4개, attempts 2 통과 |
| `sh -n scripts/compose-smoke.sh`, `git diff --check` | 통과 |

기본 E2E 단계의 6개 제외는 시나리오별 환경 조건에 따른 것이며 fake 재시도·real/real 복구는
각각 전용 단계에서 실제 실행했다. 실제 공급자 분류·요약 4개는 이번 Compose 검사 범위 밖이다.
기존 Starlette/httpx deprecation 경고가 있다. 권한 없는 캐시 회귀 fixture는 종료 시 권한을
복원하도록 정리했다. 구현 과정의 초기 fixture 잔재 정리 경고와 테스트 실패는 구분한다.
GitHub 최종 head 검사 결과와 검증 대상 SHA는 게시한 PR 본문에서 확정한다.

## 최소 서버 GPU 검증 인계

**실제 GPU 검증은 아직 실행하지 않았다.** 현재 개발 환경은 macOS이며 운영 서버 접속 별칭·
저장소 위치·허가된 입력 선택 정보 또는 사용자 실행 결과를 기다리고 있다.
이번 변경은 GPU worker의 처리기 구성 경로를 건드리므로 실제 검증이 필요하다.
104의 성공 보고를 이번 커밋의 검증으로 대체하지 않는다.

검증 대상은 이 PR의 CI 통과 최종 head다. 해당 SHA를 별도 checkout에서 `git rev-parse HEAD`로
확인하고 결과에 함께 기록한다. 서버 내부 `.env.r9-inspection`에 다음을 준비한다.

- 운영과 다른 Compose project, 새 빈 DB·입력·출력 디렉터리, 사용 가능한 루프백 포트.
- `DATA_ROOT`, `RECORDING_INPUT_HOST_DIR`, `TRANSCRIPT_HOST_DIR`, `DOCUMENT_HOST_DIR`를
  모두 해당 검증 디렉터리로 지정한다. 컨테이너 내부 경로는 compose 기본 `/data/...`를 쓴다.
- `APP_RUN_UID/GID`, 읽기 가능한 허가 입력 한 건, 쓰기 가능한 모델·NLTK 캐시.
- `SPEECH_MODE=real`, `DOCUMENT_MODE=real`, `WHISPER_DEVICE=cuda`와 기존 승인된 모델 설정.
  `HF_TOKEN`, `LLM_API_KEY`는 서버 내부 환경 파일에만 넣는다. API에는 Compose 설계상 LLM 키가 없다.
  공급자 URL·모델·context·timeout은 실제 worker 설정을 사용한다.

아래 명령은 **서버 전용 절차이며 로컬에서 실행한 결과가 아니다**. 비공개 원문·경로·키는
출력하지 않는다. GPU 접근 확인은 에이전트가 실행할 경우 sandbox 밖으로 명시적으로 승인받는다.
호스트·런타임 설치를 바꾸지 않으므로 별도 호스트 점검 대신 실제 Compose worker의 GPU 접근만 확인한다.

```sh
r9dc() {
  docker compose --env-file .env.r9-inspection -p r9-api-inspection \
    -f compose.yaml -f compose.gpu.yaml "$@"
}
git rev-parse HEAD
r9dc build api worker web
r9dc run --rm --no-deps worker nvidia-smi
r9dc up --no-deps --wait api web
```

새 입력 디렉터리에 허가된 음성 한 건만 둔다. worker를 시작하기 전에 아래 명령으로 합성 실패
이력을 만들고 상세 GET·재시도 POST를 검사한다. 운영 DB에서는 실행하지 않는다.

```sh
r9dc exec -T api python - <<'PY'
import json
import logging
import urllib.request

logging.disable(logging.CRITICAL)

def main():
    from app.config import Settings
    from app.db import connect
    from app.ingest import ingest_file
    from app.jobs import claim_next_job, fail_job
    s = Settings()
    with connect(s.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 0
    sources = [p for p in s.recording_input_dir.iterdir() if p.is_file()]
    assert len(sources) == 1
    ingest_file(s.database_path, sources[0])
    job = claim_next_job(s.database_path)
    assert job is not None and job.kind == "transcribe"
    fail_job(s.database_path, job.id, "ARTIFACT_IO_ERROR", "isolated verification")
    url = "http://127.0.0.1:8000/api/recordings/" + job.recording_id
    with urllib.request.urlopen(url, timeout=20) as response:
        assert response.status == 200
    payload = json.dumps({"job_id": job.id, "expected_revision": 1}).encode()
    request = urllib.request.Request(
        url + "/retry", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        assert response.status == 202 and json.load(response)["created"]
    with urllib.request.urlopen(request, timeout=20) as response:
        assert response.status == 202 and not json.load(response)["created"]
    print(json.dumps({"detail_http": 200, "retry_http": 202, "duplicate_reused": True}))

try:
    main()
except Exception as error:
    print(json.dumps({"check": "retry_seed", "exception_type": type(error).__name__}))
    raise SystemExit(1)
PY
r9dc up --no-deps -d worker
r9dc logs --no-log-prefix worker \
  | jq -R 'fromjson? | select(.event == "job_succeeded" or .event == "job_failed") | {event,stage,attempt,error_code}'
```

전사 처리 후 전용 UI에서 새 transcribe job 성공, 후속 작업 진행, 실제 전사 artifact를 확인한다.
화자 확인이 필요하면 해당 UI 절차를 거친다. 아래 집계는 원문·경로 없이 DB 결과를 확인한다.

```sh
r9dc exec -T api python - <<'PY'
import json
from app.config import Settings
from app.db import connect
s = Settings()
with connect(s.database_path) as connection:
    rows = connection.execute(
        "SELECT kind, status, attempts, error_code FROM jobs ORDER BY created_at"
    ).fetchall()
    print(json.dumps({"jobs": [dict(row) for row in rows]}))
    counts = connection.execute(
        "SELECT kind, COUNT(*) AS count FROM artifacts GROUP BY kind"
    ).fetchall()
    print(json.dumps({"artifacts": [dict(row) for row in counts]}))
PY
```

기대 결과는 원 transcribe 실패 1개 보존, 새 transcribe 성공 1개(attempts 1), 실제 전사 artifact와
후속 작업 진행이다. 생성된 transcript의 음성 모델 fingerprint도 서버 안에서 확인한다.
real 문서 어댑터의 실제 분류·요약 결과는 후속 단계에 도달한 범위만 기록한다.
접근 거부·요약 출력 오류가 있으면 해당 단계 미검증을 분리하고 전체 성공으로 보고하지 않는다.
R6 화자 임베딩 접근·평가 제한은 유지하며, 이번 검사 때문에 성능·강제 종료 검사를 반복하지 않는다.
결과 검토 후 같은 `r9dc down --remove-orphans`로 종료하며 검증 데이터는 결과 확인까지 보존한다.

운영 API 이미지 갱신 후 읽기 전용 상세 HTTP 집계는 105의 진단 명령을 사용한다.
현재 운영 서비스의 갱신·재조회는 실행하지 않았다. 운영 DB에 테스트 job을 등록하지 않는다.
R9 전체는 IN PROGRESS이며 R9-04 백업·복원과 간헐적 SUMMARY_INVALID_OUTPUT는 후속 범위다.
PR은 게시하되 병합하지 않는다. 서버 결과를 확보하면 같은 브랜치에 기록을 추가한다.
