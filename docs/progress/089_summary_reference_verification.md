# 요약 근거 시간 수정 전체 검증과 서버 인계

작성일: 2026-09-08. 구현 커밋: `94e8bb3` (앞선 참조 계약 `deca442` 포함).
독립 hotfix PR: `fix/summary-evidence-timestamps → main`. 선행·후속 스택 없음.
086 계획을 087 참조 계약, 088 fingerprint·통합, 이 문서의 검증·인계로 수행했다.

## 로컬 검증

기존 .venv에서 Makefile의 uv run 뒤 명령을 직접 실행했다.
frontend는 Makefile과 같은 npm 명령을 실행했다.

| 검사 | 명령 | 결과 |
| --- | --- | --- |
| Python format | `.venv/bin/ruff format --check backend` | 97개 파일 통과 |
| Python lint | `.venv/bin/ruff check backend` | 통과 |
| Python typecheck | `.venv/bin/mypy` | 96개 파일 통과 |
| OpenAPI | `.venv/bin/python -m app.openapi --check` | 통과, 외부 계약 변경 없음 |
| backend unit | `.venv/bin/pytest backend/tests/unit -q` | 468 통과 |
| backend integration | `.venv/bin/pytest backend/tests/integration -q` | 55 통과 |
| frontend format/lint/typecheck | `npm --prefix frontend run format:check`, `lint`, `typecheck` | 통과 |
| 생성 API 타입 | `npm --prefix frontend run api:types:check` | 통과 |
| frontend unit | `make test-frontend` | 4개 파일, 33 통과 |
| diff | `git diff --check` | 통과 |

기존 Starlette/httpx deprecation 경고 1건이 있다.
공개 자료의 테스트 transport로 다섯 범주·장문 평가를 수행했으며 실제 공급자 호출은 없다.
로컬 Compose/브라우저 smoke는 실행하지 않았다. 게시 PR의 GitHub Actions
`quality-and-tests`와 `compose-smoke`에서 최종 head의 결과를 확인한다.

실제 NVIDIA/GPU 검증은 불필요하다. 호스팅 요약 API의 CPU 참조 검증·시간 연결 경로만
바꾸며 GPU 실행·CUDA/NVIDIA 의존성·장치 선택·컨테이너 런타임을 사용하거나 변경하지 않는다.

## 서버 갱신 전 반드시 확인할 사항

운영 배포·재시작·유료 요청은 이번 개발 작업에서 실행하지 않았다.
다음은 운영 담당자가 수행할 별도 단계다. 원본·credential·비공개 경로를 결과에 첨부하지 않는다.

**기존 대기/실행 작업을 정상 종료한 뒤 API와 worker를 같은 커밋으로 갱신한다.**
088에서 구버전 fingerprint 작업이 새 worker에서 건너뛰어지고 결과물 없이 succeeded로
기록되는 기존 동작을 확인했다. recording은 SUMMARIZING에 남아 수동 재요청도 막힐 수 있다.
이를 새 버전의 요약 성공으로 보고하지 않는다. fingerprint나 revision을 DB에서 수정하지 않는다.
기존 완료 artifact는 보존되며 fingerprint 변경만으로 stale 표시·일괄 재요약되지 않는다.

1. 신규 수동 요청과 입력 유입을 잠시 중단한다. 아래 배열을 기존 운영 project·환경 파일·
   Compose 구성과 동일하게 맞춘다. 모든 데이터 mount는 기존 절대 경로를 유지한다.
   작업이 남았으면 기존 버전에서 정상 종료를 기다린다. 아래 조회는 상태별 건수만 출력한다.

   ```bash
   summary_compose=(docker compose
     --project-name '기존-운영-project'
     --env-file '/운영/환경파일의/절대경로'
     -f compose.yaml -f compose.gpu.yaml)
   "${summary_compose[@]}" exec -T worker python - <<'PY'
   import json
   from app.config import Settings
   from app.db import connect
   with connect(Settings().database_path) as connection:
       rows = connection.execute(
           "SELECT kind, status, COUNT(*) AS count FROM jobs "
           "WHERE status IN ('queued', 'running') GROUP BY kind, status"
       ).fetchall()
   print(json.dumps([dict(row) for row in rows]))
   PY
   ```

   결과가 빈 목록이고 신규 유입이 멈춘 것을 확인한 후 다음 단계로 진행한다.
   실패 작업 때문에 막혀 있으면 해당 오류를 먼저 처리한다. 임의 DB 상태 변경으로 넘기지 않는다.
   기존 로그 중 필요한 허용 필드 진단은 컨테이너 재생성 전에 보관한다.

2. 원격 PR의 CI가 통과한 정확한 head를 별도 checkout으로 준비한다.
   다음 명령의 커밋은 구현 검증 기준이며 PR에 후속 수정이 있으면 최종 CI 통과 커밋을 사용한다.

   ```bash
   git fetch origin fix/summary-evidence-timestamps
   git worktree add --detach ../summary-reference-release 94e8bb3
   cd ../summary-reference-release
   git rev-parse HEAD
   "${summary_compose[@]}" stop api worker
   "${summary_compose[@]}" up -d --build --no-deps api worker
   "${summary_compose[@]}" ps api worker
   ```

   API만 또는 worker만 갱신하지 않는다. Compose GPU override는 기존 서버 구성을 유지하기
   위한 것이며 이 작업의 GPU 검증 명령이 아니다. CPU 운영 구성은 기존대로 override를 제외한다.

3. 새 모듈을 포함한 관련 파일의 소스/컨테이너 해시와 API/worker fingerprint를 비교한다.
   각 서비스에서 동일한 schema·adapter·설정 계약이 실행됨을 확인하기 전 실제 요청을 하지 않는다.

   ```bash
   summary_modules=(backend/app/schema.py backend/app/summary.py
     backend/app/summary_references.py backend/app/openai_summary.py
     backend/app/summary_eval.py backend/app/pipeline.py)
   sha256sum "${summary_modules[@]}"
   for service in api worker; do
     "${summary_compose[@]}" exec -T "$service" sha256sum "${summary_modules[@]}"
     "${summary_compose[@]}" exec -T "$service" python - <<'PY'
   from app.config import Settings
   from app.summary import configured_summary_settings_fingerprint
   print(configured_summary_settings_fingerprint(Settings(), '강의'))
   PY
   done
   ```

4. 원래 실패 대상의 revision 6이 그대로인지 UI에서 확인한다. 현재 revision이 바뀌었다면
   새 입력에 대한 검증임을 기록하고 DB revision을 되돌리지 않는다.
   대상 하나를 수동 요약 요청한다. 실제 공급자 비용이 발생한다.
   새 job ID와 실제 input_revision을 기준으로 [085의 허용 필드 로그 필터](085_summary_validation_verification.md)를 사용한다.
   같은 유료 요청을 반복하지 말고 실패 사유가 바뀌면 먼저 새 사유를 확인한다.
5. 최종 summary_validation_succeeded, job 완료, JSON/Markdown 생성 및 UI 조회를 확인한다.
   서버 내부에서 모든 근거의 segment ID와 원본 start_ms/end_ms를 비교한다.
   외부 보고에는 성공 여부·검사 근거 수·불일치 건수만 포함하고 원문/quote/시간 값은 제외한다.
6. 복구가 필요하면 신규 요청을 중단하고 신버전 작업도 정상 종료한 뒤 API와 worker를
   함께 기존 검증 버전으로 되돌린다. 동일 데이터 mount를 유지하고 완료 artifact를 삭제하지 않는다.
   신버전 fingerprint의 대기 작업을 구버전 worker에 넘기는 것도 피한다.

## 완료 범위와 로드맵

코드와 공개 회귀 검증은 완료했다. PR 게시 후 원격 CI와 base/head를 확인하며,
운영 대상의 실제 성공과 사용자 요청에 따른 PR 병합 전까지 R8은 BLOCKED다.
R9·R10은 NOT STARTED이고 R6의 모델 접근 승인·평가 표본 blocker도 유지한다.
시간 생성 오류의 구조적 제거가 모든 의미적 요약 오류의 해결을 보장하지 않는다.
