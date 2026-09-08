# 요약 원문 연결 전체 검증과 서버 인계

작성일: 2026-09-08. 구현 커밋: `60541c1` (앞선 `5dbeeb6` 포함).
독립 hotfix PR: `fix/summary-source-quotes → main`. 선행 #54는 main 0a33cb9에 병합됐다.
열린 선행·후속 스택은 없으며 090 계획 → 091 원본 연결 → 092 fingerprint·통합 → 이 문서 순서다.

## 로컬 검증

기존 .venv에서 Makefile의 uv run 뒤 명령을 직접 실행했다.
frontend는 Makefile과 동일한 npm 명령을 실행했다.

| 검사 | 실제 명령 | 결과 |
| --- | --- | --- |
| Python format | `.venv/bin/ruff format --check backend` | 97개 파일 통과 |
| Python lint | `.venv/bin/ruff check backend` | 통과 |
| Python typecheck | `.venv/bin/mypy` | 96개 파일 통과 |
| OpenAPI | `.venv/bin/python -m app.openapi --check` | 통과, 외부 계약 변경 없음 |
| backend unit | `.venv/bin/pytest backend/tests/unit -q` | 491 통과 |
| backend integration | `.venv/bin/pytest backend/tests/integration -q` | 56 통과 |
| frontend format | `npm --prefix frontend run format:check` | 통과 |
| frontend lint | `npm --prefix frontend run lint` | 통과 |
| frontend typecheck | `npm --prefix frontend run typecheck` | 통과 |
| 생성 API 타입 | `npm --prefix frontend run api:types:check` | 통과 |
| frontend unit | `make test-frontend` | 4개 파일, 33 통과 |
| diff | `git diff --check` | 통과 |

기존 Starlette/httpx deprecation 경고 1종이 있다. 공개 다섯 범주·45분 장문 평가 회귀는
테스트 transport로 수행했다. 유료 공급자 요청은 실행하지 않았다.
로컬 Compose/브라우저 smoke는 실행하지 않았으며 게시 후 최종 head의 GitHub Actions
`quality-and-tests`, `compose-smoke` 결과와 base/head를 확인해 PR 본문에 기록한다.
compose-smoke에는 Compose와 브라우저 smoke가 포함된다.

실제 NVIDIA/GPU 검증은 불필요하다. 변경은 호스팅 요약 API의 CPU 근거 연결 경로이며
GPU 실행·CUDA/NVIDIA 의존성·장치 선택·컨테이너 런타임을 사용하거나 변경하지 않는다.

## 서버 인수 절차

운영 배포·재시작·유료 요약은 별도 승인된 운영 단계에서 수행한다.
기존 [089 서버 갱신 절차](089_summary_reference_verification.md)의 project·환경 파일·
데이터 mount 유지, 작업 건수 조회, API/worker 동시 갱신 및 복구 절차를 따른다.
**089의 예시 브랜치·커밋·revision을 그대로 사용하지 말고 아래 기준으로 바꾼다.**

1. 신규 입력과 수동 요청을 잠시 중단하고 기존 대기/실행 작업을 기존 버전에서 정상 종료한다.
   092의 회귀처럼 fingerprint가 다른 작업은 새 worker에서 건너뛰어져도 job이 succeeded로
   기록될 수 있다. artifact가 없고 recording은 SUMMARIZING에 남으므로 이를 요약 성공으로
   보고하지 않는다. DB fingerprint·revision·작업 상태를 임의 변경해 통과시키지 않는다.
2. 이번 PR `fix/summary-source-quotes`의 **최종 CI 통과 head**를 조회해 별도 checkout으로
   준비한다. 예전 089의 94e8bb3이나 이 문서의 구현 중간 커밋을 배포 기준으로 고정하지 않는다.
   기존 운영 Compose project·환경 파일·데이터 mount를 유지한 채 API와 worker를 함께 갱신한다.
3. 소스와 두 컨테이너의 schema.py, summary.py, summary_references.py, openai_summary.py,
   summary_eval.py, pipeline.py 해시를 비교한다. 동일 운영 설정에서 API configured fingerprint와
   worker 어댑터 fingerprint가 일치하는지 확인한다. 기대 계약은 다음과 같다.

   - prompt_version: `openai-grounded-summary-v4`
   - provider_schema_version: `3`
   - evidence_time_strategy: `source-segment-time-v1`
   - evidence_quote_strategy: `source-segment-text-v1`
   - 외부 schema_version/template_version: `1`

4. 이번 실패 대상의 **현재 revision**을 UI에서 확인한다. 관측 로그는 revision 2였지만
   현재도 2라고 가정하지 않는다. 달라졌으면 새 입력에 대한 검증임을 기록한다.
   해당 대상 한 건을 명시적으로 요약 요청하고 실제 job과 input_revision으로 허용 필드 로그를
   추적한다. [085의 안전한 진단 필터](085_summary_validation_verification.md)를 사용한다.
5. 최종 summary_validation_succeeded, job 완료, JSON/Markdown 생성과 UI 조회를 확인한다.
   서버 내부에서 해당 input_revision 원본과 모든 근거의 ID·시간·quote 전체 일치를 검사한다.
   외부 보고에는 검사한 근거 수와 ID/시간/원문 불일치 건수만 남긴다.
   원문·실제 quote·개인 식별자·비공개 경로·credential은 로그나 진행 문서에 남기지 않는다.
6. 실패하면 오류 사유·단계·시도·안전한 field_path를 확인한 뒤 조치한다. 같은 유료 요청을
   무작정 반복하지 않는다. 복구 시 새 요청을 중단하고 신버전 작업도 정상 종료한 뒤
   API와 worker를 함께 기존 검증 버전으로 되돌린다. 기존 mount와 완료 artifact를 보존하고
   신버전 fingerprint의 대기 작업을 구버전 worker에 넘기지 않는다.

## 사용자 영향과 완료 범위

새 요약의 quote는 모델이 고른 부분 인용이 아니라 원본 segment 전체 문장이다.
분할 입력이어도 원본 전체를 연결하므로 slice 범위만의 인용을 뜻하지 않는다.
긴 문장을 여러 근거에서 참조하면 저장 JSON이 커질 수 있다. 절단·중복 제거는 하지 않았다.
기존 완료 artifact의 부분 인용·null과 공개 API·OpenAPI·DB·저장 JSON 구조는 유지한다.
원문 일치는 의미적으로 올바른 근거 선택이나 요약 품질 전체를 보장하지 않는다.

개발 완료 기준은 구현·공개 회귀·최종 CI 통과·한국어 PR 게시다.
운영 성공 확인과 PR 병합 전까지 R8은 BLOCKED, R9·R10은 NOT STARTED를 유지한다.
R6의 모델 접근 승인·평가 표본 blocker도 유지한다.
재시도·timeout·모델·교정 대화·자동 일괄 재요약·기존 작업 상태 처리 변경은 비범위다.
