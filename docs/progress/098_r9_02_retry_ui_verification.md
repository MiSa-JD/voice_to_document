# R9-02 재시도 UI와 브라우저 검증

작성일: 2026-09-09. 브랜치: `feature/r9-02-job-retry-ui → feature/r9-01-stale-job-recovery`.
선행 [PR #56](https://github.com/MiSa-JD/voice_to_document/pull/56). 후속 R9-03 로그·운영 현황.

처리 이력에서 단계·상태·시도 횟수·오류 코드·한국어 분류·설명·다음 실행 시각·가능한
복구 동작을 표시한다. 서버가 retry를 허용한 작업만 버튼을 제공하고, 요약·STT 재수행은
기존 전용 영역으로 연결한다. 요청 중 버튼을 비활성화하고 성공·409 충돌 후 최신 상태를
다시 조회한다. Enter 키 제출과 상태 메시지를 지원한다. 상세 polling은 녹음 상태뿐 아니라
활성 job도 확인해 화자 처리·render·backoff를 놓치지 않는다.

검증 명령은 096과 동일한 .venv 직접 명령 및 npm 명령을 사용했다.

| 검사 | 결과 |
| --- | --- |
| Python format/lint/mypy | 103개 format, 102개 typecheck 통과 |
| OpenAPI와 생성 타입 검사 | 통과 |
| backend unit + integration | 577개 통과 |
| frontend format/lint/typecheck | 통과 |
| frontend unit | 35개 통과 |
| git diff --check | 통과 |
| make compose-smoke | 기본 브라우저 3개, 재시작 보존 1개, 복구 probe, 재시도 브라우저 1개 통과 |

재시도 브라우저 검증은 격리 Compose에서 worker를 잠시 정지하고 공개 fixture의 render를
안전한 실패 코드로 종료한 뒤 UI의 Enter 키로 새 작업을 등록한다. worker 재개 후 성공과
원 실패 이력 유지·segment ID/내용 보존을 확인한다. 기본 재시작 보존 검증 이후 별도로
실행해 fixture 변경이 기존 고정값 검증에 영향을 주지 않는다. 처음 동시 실행한 검증의
fixture 간섭을 확인해 실행 순서를 분리했으며 수정 후 전체 Compose 검사가 통과했다.
실제 공급자 전용 브라우저 4개는 fake 환경이므로 제외한다.

실제 GPU 검증은 미완료다. 096의 서버 전용 project·DB·출력 디렉터리에서 실제 GPU 실패 후
새 job 재시도를 확인하고 결과를 인계받는다. 최종 실패한 STT 재수행은 삭제된 힌트를 재사용하지
않고 전용 폼에서 새로 입력한다. R6 blocker 및 R9 전체 IN PROGRESS 상태는 유지한다.
