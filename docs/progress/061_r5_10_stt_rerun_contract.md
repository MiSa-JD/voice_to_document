# R5-10 사용자 힌트 기반 STT 재수행 계약

## 구현

- `POST /api/recordings/{id}/retranscriptions`는 revision, `auto/ko/en/ja`, 내용 설명, 전문용어,
  영향 확인을 검증하고 202 request/job 계약을 반환한다.
- 활성 음성 작업, revision 충돌, 같은 입력 중복을 거부하며 latest API는 힌트 원문 없이 언어·segment·
  미확정 화자·history 상태를 제공한다.
- 힌트 원문은 실행 중에만 DB에 보관하고 성공 또는 최종 실패 시 삭제한다. 메타데이터에는 언어,
  모델/config fingerprint, 힌트 적용 여부, SHA-256만 남긴다.
- fake/WhisperX adapter에 요청별 language와 initial prompt 전달을 추가했다.
- 새 음성 결과는 transcript root에 staging한 뒤 DB revision, segment, recording speaker, classification
  stale 상태와 함께 한 트랜잭션에서 전환한다. 실패하면 기존 성공 결과를 유지한다.
- 이전 JSON/Markdown/summary는 `APP_DATA_DIR/history/{recording_id}/{revision}`에 보존하며 API에는
  민감 경로 대신 `app_data/history` 위치만 공개한다.

## 검증

- API validation/충돌/중복, adapter 전달, hint 삭제, staging 실패 보존, 원자적 전환, history 보존,
  민감정보 비노출을 unit/integration test로 확인한다.
- 전체 정적 검사와 테스트 결과는 PR 본문에 기록한다.

## 비범위

- 입력 form, 영향 확인 화면, polling 결과 비교 UI는 R5-11에서 다룬다.
