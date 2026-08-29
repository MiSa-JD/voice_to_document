# Flat Markdown recovery와 기존 결과 이전

- worker 시작 시 현재 revision의 Markdown artifact 중 UUID 경로이거나 파일이 누락된 항목을 점검한다.
- transcript JSON identity/revision/content hash와 DB segment·classification을 검증한 뒤 STT 없이 Markdown을 재렌더한다.
- 새 flat 파일 저장과 artifact 갱신 후에만 기존 UUID Markdown과 비어 있는 상위 디렉터리를 제거한다.
- 실패 시 recording 상태와 기존 artifact를 유지하고 recording ID와 오류 코드만 구조화 로그와 audit event에 기록한다.
- 재시작할 때 같은 항목을 다시 시도하며 정상 flat artifact는 건너뛴다.
