# 요약 세부 진단 전체 검증과 서버 인계

## 결과와 범위

082 계획을 083 오류 분류, 084 응답별 로깅으로 구현했다.
검증된 구현 커밋은 `2c24423d32000b45d4082f105c8386ad8e459b9d`이다.
이 문서와 로드맵 갱신은 세 번째 문서 커밋으로 분리한다.
독립 PR 관계는 `fix/summary-validation-diagnostics → main`이며 선행·후속 스택은 없다.

운영 서버 배포·재시작과 실제 유료 요약 요청은 수행하지 않았다.
진단 기능만으로 운영 문제 해결을 선언하지 않는다. R8은 BLOCKED,
R9·R10은 NOT STARTED다. R6의 모델 접근·평가 표본 blocker도 유지한다.

## 로컬 검증 (2026-09-07)

기존 .venv를 사용해 Makefile의 `uv run` 뒤 명령을 직접 실행했다.
frontend는 동일한 npm 명령을 실행했다.

| 기본 검사 | 실행 명령 | 결과 |
| --- | --- | --- |
| check-format | `.venv/bin/ruff format --check backend`, `npm --prefix frontend run format:check` | 통과 |
| lint | `.venv/bin/ruff check backend`, `npm --prefix frontend run lint` | 통과 |
| typecheck | `.venv/bin/mypy`, `npm --prefix frontend run typecheck` | 95개 Python 파일 및 frontend 통과 |
| api-schema-check | `.venv/bin/python -m app.openapi --check`, `npm --prefix frontend run api:types:check` | 통과, 외부 계약 변경 없음 |
| test-unit | `.venv/bin/pytest backend/tests/unit -q` | 449 통과 |
| test-integration | `.venv/bin/pytest backend/tests/integration -q` | 52 통과 |
| test-frontend | `make test-frontend` | 4개 파일, 33 통과 |
| diff | `git diff --check` | 통과 |

backend에는 기존 Starlette/httpx deprecation 경고 1건이 있다.
추가로 origin/main의 기존 어댑터를 별도 namespace에 읽어 동일 설정의
fingerprint 전체가 현재 구현과 일치함을 비교했다.
실제 JSON formatter, 저장 오류 메시지, 동시 호출 맥락 분리 및 worker 완료 연결을 검증했다.
로컬 Compose/브라우저 smoke는 실행하지 않았으며 PR의 GitHub Actions에서 확인한다.

실제 NVIDIA/GPU 검증은 불필요하다. 호스팅 요약 API의 CPU 진단 경로만 바꾸며
GPU 실행·의존성·장치 선택·컨테이너 런타임에 영향을 주지 않는다.

## 서버 갱신 절차 — 별도 운영 단계

아래 명령은 운영 서버에서 담당자가 수행할 안내다.
진행 중인 worker 작업이 끝난 후 갱신한다.
보관할 로그는 컨테이너 재생성 전에 확보한다. 이미 사라진 컨테이너 로그나
진단 기능 이전의 로그에서 새 상세 필드를 복구할 수는 없다.

1. 원격 브랜치에서 검증 커밋을 별도 checkout으로 준비한다.
   기존 운영 checkout을 사용할 경우에도 로컬 변경을 보존하고 해당 커밋을 정확히 확인한다.

   ```bash
   git fetch origin fix/summary-validation-diagnostics
   git worktree add --detach ../summary-diagnostics-release 2c24423d32000b45d4082f105c8386ad8e459b9d
   cd ../summary-diagnostics-release
   git rev-parse HEAD
   ```

2. 기존 운영 환경 파일, Compose project 이름과 데이터 mount를 그대로 사용한다.
   별도 checkout에서 상대 경로 기반 기본값을 사용하면 다른 데이터 디렉터리를 열 수 있으므로
   운영에서 사용하던 절대 경로·project·env-file 설정을 동일하게 지정한다.
   아래 Bash 배열의 두 경로/이름을 실제 운영 설정으로 바꾼다.
   기존 GPU override를 쓰는 서버용 예시이며, CPU 서버는 기존 구성대로 GPU 파일만 제외한다.

   ```bash
   summary_compose=(docker compose
     --project-name '기존-운영-project'
     --env-file '/운영/환경파일의/절대경로'
     -f compose.yaml -f compose.gpu.yaml)
   "${summary_compose[@]}" up -d --build --no-deps worker
   "${summary_compose[@]}" ps worker
   ```

3. 소스와 실행 컨테이너의 변경 모듈 해시를 비교한다. 출력은 저장소 상대 파일명과 해시뿐이다.
   일치 여부를 확인하기 전에 재현을 요청하지 않는다.

   ```bash
   sha256sum backend/app/{schema,summary,openai_summary,pipeline,adapters,summary_eval}.py
   "${summary_compose[@]}" exec -T worker sha256sum      backend/app/schema.py backend/app/summary.py backend/app/openai_summary.py      backend/app/pipeline.py backend/app/adapters.py backend/app/summary_eval.py
   ```

## 한 번의 수동 재현과 안전한 로그 수집

기존 UI에서 대상 revision을 확인하고 수동 요약을 한 번 요청한다.
실제 공급자 비용이 발생한다. 이번 구현 작업에서 실행한 요청은 모두 테스트 transport다.
새 요청 응답/상세 화면의 **새 job ID**를 사용한다.
이전 실패 job ID나 현재 화면 revision이 실제 새 요청의 입력과 같다고 추정하지 않는다.

아래 명령은 앞 절의 `summary_compose` 배열을 유지한 Bash에서 실행한다.
`summary_input_revision`은 새 요청의 expected_revision에 맞추고,
`summary_request_started.input_revision`과 대조한다. 출력이 없으면 우선 시간 범위,
새 job ID, revision, 실제 컨테이너 해시를 확인하고 같은 유료 요청을 반복하지 않는다.
재시도 대기가 길면 `--since` 범위를 늘린다.
**재현 이후 다음 컨테이너 재생성 전에 이 결과를 저장한다.**

```bash
summary_job_id='새-수동-요청의-job-id'
summary_input_revision=2
set -o pipefail
"${summary_compose[@]}" logs --no-color --no-log-prefix --since 30m worker 2>&1 |
  jq -Rrc --arg job "$summary_job_id" --argjson revision "$summary_input_revision" '
    fromjson? | select(type == "object")
    | select(.job_id == $job and .input_revision == $revision)
    | select(.event == "summary_request_started"
          or .event == "summary_validation_failed"
          or .event == "summary_validation_succeeded")
    | {timestamp, level, service, event, job_id, input_revision, job_attempt,
       template, phase, chunk_index, chunk_count, provider_attempt,
       input_chars, segment_count, elapsed_seconds, failure_reason,
       validation_errors: [.validation_errors[]? | {validation_type, field_path}],
       error_count, omitted_error_count}
    | with_entries(select(.value != null))
  ' > summary-diagnostics.jsonl
cat summary-diagnostics.jsonl
```

허용한 최상위 필드와 상세 오류의 두 필드만 출력한다.
transcript·응답·quote·값·키·비공개 경로·예외 문자열·traceback을 복사하지 않는다.
원본 `docker logs`나 환경 변수 전체를 별도로 붙여 넣지 않는다.
수집 필터는 공개 합성 JSON으로 다른 job/revision/이벤트와 추가 비밀 필드 제거를 검증했다.

## 결과 해석과 남은 완료 조건

- 동일 phase/chunk의 provider_attempt 1 실패 → 2 성공이면 교정 성공이다.
- 1·2 실패의 failure_reason 및 validation_errors를 비교하면 같은 오류/다른 오류를 구분한다.
- field_path는 전체 응답의 purpose·action_items 등 또는 chunk의 facts 배열 기준이다.
- input_chars/segment_count 정의는 [084](084_summary_validation_logging.md)를 따른다.
- 오류가 5건을 넘으면 omitted_error_count를 확인한다. 원문 추가 수집이 기본 대응은 아니다.
- worker 최종 결과는 같은 job ID의 UI 상태로 확인한다.
  중간 chunk 성공은 전체 작업 완료를 의미하지 않는다.
- 사례 B의 현재 revision 3 재현과 보존된 revision 2 재현은 별개다.
  DB revision을 되돌리거나 운영 원문을 공개 fixture에 복사하지 않는다.

진단에서 확인한 사유에 맞는 최소 수정과 공개 회귀 입력을 만들고,
운영 재검증·관련 PR 병합까지 확인한 뒤 R8 완료 여부를 판단한다.
