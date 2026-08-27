# R7-01 범주·출력 설정

## 상태

- backend-only 선행 트랙의 P1 완료
- R5, R6, R7 M5는 완료 처리하지 않음

## 변경

- `CATEGORIES`와 `AUTO_SUMMARY_CATEGORIES`의 빈 값, 중복, 미허용 값을 시작 시 거부한다.
- 표시 이름과 NFKC 정규화된 안전한 category slug를 분리하고 slug 충돌을 거부한다.
- `DOCUMENT_ROOT`를 문서 출력 루트로 추가하고 이전 `SUMMARY_ROOT` 환경 변수도 호환한다.
- 입력, transcript, speaker, document, app-data root의 절대 경로, 존재 여부, 권한, 비중첩을 검증한다.
- 확정된 `docs/04_stt_markdown_mvp_plan.md`를 추적한다.

## 검증

- 범주 parsing, slug 안전성·충돌, document root alias와 root 중첩 unit test
- transcript 본문, token, 입력 절대 경로를 이 문서에 기록하지 않음
