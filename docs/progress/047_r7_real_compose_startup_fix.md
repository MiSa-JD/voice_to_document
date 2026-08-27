# R7 real GPU Compose 시작 오류 수정

## 상태

- `fix/r7-real-compose-startup` 완료
- R5, R6 및 R7 M5 전체는 완료 처리하지 않음

## 원인

- Compose는 `SPEECH_MODE=real`을 API와 worker에 공통 전달한다.
- API에는 worker 전용 model cache가 mount되지 않지만, 기존 설정 검증이 API에서도
  `MODEL_CACHE_ROOT` 존재 여부를 검사해 API가 시작 직후 종료됐다.
- API health 실패 때문에 worker와 web도 dependency 조건을 통과하지 못했다.

## 변경

- real speech의 `HF_TOKEN`과 `MODEL_CACHE_ROOT` 검증을 worker service에만 적용한다.
- API는 real speech 상태를 표시하되 worker 전용 token/cache를 요구하지 않는다.
- worker의 cache 절대 경로, 존재 여부, 쓰기 권한 및 결과 root 비중첩 검증은 유지한다.
- README에 fake stack과 real GPU STT→Markdown stack의 실행·출력 경로를 구분했다.

## 개인정보

- 검증 로그와 이 문서에 token, transcript 본문, private 입력 절대 경로를 기록하지 않는다.

## 검증

- `make check-format`, `make lint`, `make typecheck`, `make api-schema-check` 통과
- `make test`: unit 245개, frontend 9개, integration 11개 통과
- 임시 격리 root에서 real GPU Compose 전체 stack의 API·worker·web 기동 및 health 통과
- private 다중 화자 m4a를 worker 감지 방식으로 처리해 revision 1, segment 144개, 임시 화자
  2명을 확인했다.
- 동일 revision JSON/Markdown, millisecond timestamp, `SPEAKER_XX` 및 artifact 생성 검증 통과
- 검증용 Compose stack과 임시 파일 정리 완료
