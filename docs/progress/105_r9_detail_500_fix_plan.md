# R9 상세 조회 500 수정 계획 — 복구 판단과 worker 초기화 분리

작성일: 2026-09-10. 갱신일: 2026-09-12. 상태: 구현 착수 — 원래 계획과 관측 근거 보존.
구현·검증 결과와 실제 GPU 대기 상태는 [106 진행 기록](106_r9_api_recovery_inspection.md)을 따른다.
작성 시점 브랜치: `docs/r9-server-gpu-verification`.
선행: 104 서버 GPU 검증 결과 및 PR #56 → #57 → #58 → #59.

## 1. 문제와 확인 근거

사용자는 기존 녹음의 절반 가까이에서 상세 페이지가 `상세 갱신 실패`, HTTP 500을
표시한다고 보고했다. 서버의 API 컨테이너에서 실행한 진단 결과를 인계받았다.

| 항목 | 관측 결과 |
| --- | --- |
| API 모드 | `SPEECH_MODE=real`, `DOCUMENT_MODE=real` |
| API 모델 캐시 | 존재·디렉터리·쓰기 가능 여부 모두 false |
| 복구 판단용 처리기 생성 | `ValueError: model_cache_root does not exist` |
| 과거 실패 작업이 있는 녹음 | 17건, 요청한 표본 2건 모두 HTTP 500 |
| 과거 실패 작업이 없는 녹음 | 14건, 요청한 표본 2건 모두 HTTP 200 |

31건 중 17건에 실패 이력이 있다는 집계와 표본 HTTP 검사를 구분한다.
전체 17건의 HTTP 500을 직접 측정한 것으로 기록하지 않는다.
원문·원본 경로·credential은 기록하지 않는다.

확인된 호출 경로:

```text
GET /api/recordings/{recording_id}
  → jobs에 failed 이력이 있으면 job_retries.recovery_handler(settings)
  → worker.build_handler(settings)
  → RealSpeechPipelineHandler 생성
  → WhisperXConfig.__post_init__에서 모델 캐시 검사
  → ValueError → 처리되지 않은 예외 → HTTP 500
```

`compose.gpu.yaml`은 worker에 모델 캐시를 연결하지만 API에는 연결하지 않는다.
API가 상세 정보를 읽을 때 GPU 실행용 설정 검사를 요구하는 것이 결함이다.
현재 녹음 상태가 COMPLETED여도 과거 failed job이 하나 있으면 이 경로에 진입한다.
`POST /api/recordings/{recording_id}/retry`도 같은 생성 함수를 호출하므로 함께 수정한다.
서버에서 POST 실패를 직접 측정한 것은 아니며, 영향 범위는 코드 호출 관계에 근거한다.

에이전트는 별도로 누락된 모델 캐시를 지정한 Settings 객체로 생성자 호출을 실행해
동일 ValueError를 재현했다. 실제 모델 실행이나 운영 데이터 변경은 하지 않았다.

## 2. 목표와 수정 경계

목표는 모델 캐시·GPU·LLM credential이 없는 API에서도 실패 이력을 조회하고,
실제 입력 계약에 따라 수동 재시도 가능 여부를 판단할 수 있게 하는 것이다.
기존 상태·오류 정책·revision·fingerprint·artifact 검증은 유지한다.

수정은 다음 순서의 하나의 결함 수정 PR로 묶는다.

1. `job_retries.recovery_handler`의 두 API 호출자와 `recovery.inspect_recovery`의
   실제 의존성을 회귀 테스트로 고정한다. 현재 필요한 것은 settings와 분류·요약
   fingerprint이며, 음성 모델 어댑터 생성은 필요하지 않다.
2. `worker.build_handler`에 있는 문서 어댑터 구성 부분을 작은 공통 생성 함수로
   분리한다. 별도 경량 모듈에 두고 API가 worker 모듈을 import하지 않도록 한다.
   기존 OpenAI 분류 어댑터·LongTranscriptClassifier·요약 어댑터 구성을 그대로 재사용한다.
3. API의 `recovery_handler`는 원래 Settings의 의미를 보존하면서 공통 문서 어댑터와
   기존 `FakePipelineHandler` 기반 검사 객체만 구성한다. 이 객체는 호출해 작업을
   실행하지 않으며 real speech 어댑터를 생성하지 않는다.
   기존 클래스 재사용은 내부 구현 선택이며 API 설정을 fake 모드로 바꾸는 것이 아니다.
4. worker는 공통 함수에서 문서 어댑터를 받은 뒤 기존 기준으로 real/fake 음성 처리기를
   구성한다. worker credential·모델 설정·실행 동작은 그대로 전달한다.
5. API에서 사용하는 문서 어댑터의 credential은 기존처럼 빈 값으로 두고 실제 공급자를
   호출하지 않는다. HTTP 요청·모델 로더가 호출되면 즉시 실패하는 테스트로 보장한다.

공통 함수는 두 호출 경로에 필요한 최소 구성만 반환한다. 별도 실행 엔진이나 범용
팩토리 계층은 추가하지 않는다. 분류·요약 fingerprint는 API와 worker에서 동일해야 한다.
문서 모드, 모델, context 제한, prompt/schema 버전, 화자 설정 등 기존 비교 정보가
누락되거나 fake fingerprint로 대체되지 않도록 검증한다.

예상 변경 파일은 `backend/app/job_retries.py`, `backend/app/worker.py`,
문서 어댑터 공통 생성 모듈 하나와 관련 테스트다. `recovery.py`의 판단 규칙이나
프런트엔드·공개 응답 schema 변경은 기본 범위에 포함하지 않는다.

API에 `/models`를 추가 마운트하거나 GPU·LLM 키를 부여해서 우회하지 않는다.
실패 job 삭제, 기존 녹음 일괄 재전사, DB migration, 포괄적 예외 무시,
입력 검증 완화, 요약 출력 오류 수정은 이 작업에 포함하지 않는다.

## 3. 구현 전 실패 재현과 회귀 검증

기존 API integration 테스트와 worker unit·복구 integration 테스트를 확장한다.
테스트 데이터는 합성 입력만 사용한다. 필요한 경우 API 재시도 회귀를 별도 테스트 파일에 모은다.

| 조건 | 기대 결과 |
| --- | --- |
| real speech + real document, API 캐시 없음, 실패 이력 있음 | 상세 GET 200, 기존 실패 job 표시 |
| 현재 COMPLETED + 과거 failed job | 상세 GET 200, 완료 결과·실패 이력 함께 보존 |
| 실패 이력 없음 및 fake/real 문서 모드 조합 | 기존 조회 동작 유지 |
| 캐시 경로가 파일이거나 쓰기 권한 없음 | API 복구 판단이 해당 캐시에 접근하거나 의존하지 않음 |
| 현재 revision의 재시도 가능한 실패 job, 캐시·키 없음 | POST 202, 새 job 생성, 원 failed job 보존 |
| 동일 실패 job 재요청 및 동시 요청 | 기존 child 재사용, 복구 작업 중복 등록 없음 |
| 오래된 revision·활성 작업·필수 입력 누락·fingerprint 불일치 | 기존 409/복구 불가 정책 유지, 500으로 전환되지 않음 |
| 요약 재요청·전용 STT 재수행 | 기존 전용 동작 유지, 삭제된 STT 힌트 복원 없음 |
| API 검사 실행 중 음성 생성자·모델 로더·외부 HTTP 호출 감시 | 호출 0회 |
| 같은 설정의 API 검사 객체와 worker | 분류·요약 및 관련 설정 fingerprint 동일 |
| worker 실제 처리기 선택 | real/fake 선택, 어댑터 설정·credential 전달 유지 |

기존 `compose-smoke.sh`는 두 모드를 fake로 설정하므로 이 회귀를 잡지 못했다.
격리 Compose 검증에 real/real API 전용 사례를 추가한다. API에는 GPU 패키지·모델 캐시·
공급자 키를 제공하지 않고, 합성 DB/artifact에 과거 실패 이력을 준비한다.
해당 시나리오의 worker는 실행하지 않으며 POST 검증으로 생긴 job을 실제 처리하지 않는다.
브라우저에서 기존 실패 이력이 있는 상세 화면과 처리 이력이 표시되는지 확인한다.
real/real 설정에 필요한 비민감 모델 설정은 테스트 전용 값으로 주고 외부 호출은 차단한다.

## 4. 일반 검사와 최소 실제 GPU 검증

구현 후 해당 브랜치 전체 상태에서 저장소 기본 검사를 실행하고 실제 결과를 기록한다.

```sh
make check-format
make lint
make typecheck
make api-schema-check
make test-unit
make test-integration
make test-frontend
make compose-smoke
git diff --check
```

현재 환경에서 uv 실행 제약이 있으면 104와 같은 `.venv/bin/ruff`, `.venv/bin/mypy`,
`.venv/bin/python -m app.openapi --check`, `.venv/bin/pytest` 직접 명령을 사용하고 명시한다.
각 명령의 실패를 확인하고 해결한 뒤 다음 완료 판단으로 진행한다.

이번 계획 문서 자체에는 GPU 실행 경로 변경이 없어 실제 GPU 검증이 불필요하다.
상세 조회 회귀도 GPU 없이 재현·검증한다. 다만 예정된 공통 함수 분리는 GPU worker의
처리기 구성 경로도 건드리므로 구현 PR에서는 최소 실제 GPU 검증을 포함한다.
104의 기존 중단 복구 성공은 유지하되 새 커밋에서 실행한 결과와 구분한다.

최소 범위는 격리 project·DB·출력에서 허가된 입력 한 건으로 실제 worker 구성·전사와
후속 작업 진행을 확인하는 것이다. R9-02 재시도로 등록한 새 작업을 이 한 건으로 사용하면
API 등록과 worker 실행을 함께 확인할 수 있다. 삭제된 힌트가 필요한 재전사 요청은
기존 전용 입력 폼으로 처리한다. 성능 평가·batch size 탐색·전체 강제 종료 테스트는 반복하지 않는다.
화자 임베딩 모델 접근 제한은 별도 미검증 항목으로 남긴다.
실제 GPU를 현재 개발 환경에서 실행할 수 없으면 운영 서버의 격리 환경에서 실행하며,
sandbox 실패를 NVIDIA 드라이버 문제로 판단하지 않는다.

## 5. 수정 배포 후 서버 상세 조회 재확인 명령

구현·일반 검증 후 실제 운영 배포 방식에 맞는 API 이미지 갱신 명령을 확정해 인계한다.
DB 삭제·권한 변경·추가 모델 캐시 마운트는 필요하지 않다.
아래는 수정된 API가 실행된 뒤 사용자에게 인계할 읽기 점검 명령이다.
지금 실행해도 조회는 가능하지만 수정 전에는 기존 500이 재현된다.

먼저 실제 장애 서비스의 API 컨테이너를 고른다. 테스트 환경을 가리킬 수 있는 기존 dc 함수는 쓰지 않는다.

```sh
docker ps --filter label=com.docker.compose.service=api \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

아래 첫 줄만 바꿔 실행한다. DB는 읽기 전용으로 열고 녹음별 상세 GET만 수행한다.
원문·응답 본문·원본 경로·credential은 출력하지 않는다. 전체 녹음 수만큼 순차 요청한다.

```sh
R9_API_CONTAINER='여기에_API_컨테이너_이름'
docker exec -i "$R9_API_CONTAINER" python - <<'PY'
import json
import logging
import sqlite3
import urllib.error
import urllib.request
from collections import Counter

logging.disable(logging.CRITICAL)

def main():
    from app.config import Settings
    settings = Settings()
    uri = settings.database_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as connection:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute("""
            SELECT r.id, EXISTS(
                SELECT 1 FROM jobs j
                WHERE j.recording_id = r.id AND j.status = 'failed'
            ) FROM recordings r ORDER BY r.id
        """).fetchall()
    counts = Counter()
    for recording_id, failed in rows:
        result = {
            "check": "detail_http",
            "has_failed_jobs": bool(failed),
        }
        try:
            url = "http://127.0.0.1:8000/api/recordings/" + recording_id
            with urllib.request.urlopen(url, timeout=20) as response:
                result["http_status"] = response.status
        except urllib.error.HTTPError as error:
            result["http_status"] = error.code
            error.close()
        except Exception as error:
            result["exception_type"] = type(error).__name__
        counts[str(result.get("http_status", "request_error"))] += 1
    print(json.dumps({"check": "totals", "recordings": len(rows), "http": dict(counts)}))

try:
    main()
except Exception as error:
    print(json.dumps({"check": "diagnostic", "exception_type": type(error).__name__}))
PY
```

기대 결과는 삭제 등 동시 변경이 없는 기존 녹음들의 상세 GET 200이다.
이전에 실패했던 표본과 현재 COMPLETED이지만 과거 실패 이력이 있는 항목도 확인한다.
404·다른 500·timeout이 남으면 해당 ID의 원인을 별도 추적하고 전체 통과로 보고하지 않는다.
최초 집계 31건을 고정 기대값으로 쓰지 않으며 실행 시점 총수와 HTTP 집계를 함께 남긴다.
운영 DB에 새 재시도 작업을 만들지 않고, POST와 실제 실행 검증은 3·4절의 격리 환경에서 한다.

## 6. 브랜치·PR·완료 기준

구현 착수 시 GitHub에서 #56~#59가 2026-09-10에 모두 병합되었음을 확인했다.
최신 `origin/main`은 `00f782b`이며 104 기록 커밋을 포함한다. 이번 브랜치 관계는 다음과 같다.

```text
main → fix/r9-api-recovery-inspection
```

수정 PR은 `main`을 base로 하는 독립 PR이며, 한국어 제목은
`실패 이력이 있는 녹음의 상세 조회 500 수정`이다. 새 수정의 실제 GPU 검증이
완료되기 전에는 VERIFY를 유지하며, 선행 병합이나 104 결과로 이를 대체하지 않는다.
104의 GPU 복구·실패 이력 보존·기존 재전사 결과를 취소하거나 이 상세 조회 문제와 혼동하지 않는다.
PR 본문에는 새 결함, 사용자 서버 증거, 수정 범위, 실제 실행한 검증, 남은 GPU 제한,
선행·후속 링크를 한국어로 기록한다. 이번 계획은 PR 병합 권한을 부여하지 않는다.

완료 기준:

- 실패 이력 유무와 무관하게 API가 음성 실행 환경을 초기화하지 않고 상세를 반환한다.
- 수동 재시도 등록·중복 방지·revision 및 입력 충돌 정책이 유지된다.
- API와 worker의 fingerprint 의미 및 worker 처리기 구성이 유지된다.
- real/real·캐시 없는 API 조건의 회귀 테스트와 격리 Compose 검증이 통과한다.
- 일반 검사 및 수정 PR 최종 head의 CI가 통과하고 서버 재확인 결과를 기록한다.
- 필요한 최소 실제 GPU 결과 또는 구체적인 미검증 범위를 명시한다.
- 코드·테스트·진행 기록을 커밋하고 base가 main인 독립 PR로 게시한다. 병합은 별도 요청 시 수행한다.

R6 blocker, R9 전체 IN PROGRESS, R9-04 이후 작업 및 간헐적 SUMMARY_INVALID_OUTPUT
후속 범위는 유지한다. 이번 문서 작성 시에는 애플리케이션 코드를 수정하거나 서버 명령을 실행하지 않았다.

## 7. 계획 문서 검증

문서의 shell 코드 블록 3개를 `sh -n`으로 검사하고, 포함된 Python 코드를
`ast.parse`로 구문 검사했다. 상대 문서 링크 존재 여부와 새 파일의 줄 끝 공백을 확인했으며
`git diff --check`가 통과했다. 명령 구문 검사와 실제 서버 실행 결과를 구분한다.
