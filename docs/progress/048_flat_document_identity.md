# Flat Markdown 문서 identity

- schema v4에 `recordings.document_sequence`, `recordings.document_title`과 영구 sequence counter를 추가했다.
- 기존 recording은 `created_at, id` 순으로 번호를 backfill하며 삭제된 번호는 다시 사용하지 않는다.
- 최초 Markdown 렌더 직전 호출할 수 있는 transaction 기반 identity 할당과 flat 상대 경로 생성을 추가했다.
- 제목은 첫 발화의 공백 정규화, Unicode 20자 절단, 예약·제어 문자 제거와 category/`recording` fallback 계약을 따른다.
- migration, 동시 할당, 삭제 후 미재사용, 제목과 경로 단위 테스트를 추가했다.
