# R5-08 수정 후 artifact 재렌더

## 구현

- 화자 전체·개별·일괄 배정과 연결된 인물 이름 변경은 녹음 revision 증가와 `render` job 등록을
  하나의 SQLite 쓰기 트랜잭션에서 처리한다.
- 활성 render가 있으면 추가 수정을 `RENDER_IN_PROGRESS`로 거부한다.
- render worker는 기존 transcript JSON의 모델·언어·분류 메타데이터와 현재 DB segment/인물 이름을
  결합해 JSON과 Markdown만 다시 생성하며 STT·alignment·diarization을 실행하지 않는다.
- 상세 API는 현재 revision과 일치하는 summary만 노출한다. 이전 summary가 있던 녹음만 render 성공
  후 같은 revision의 summarize job을 등록한다.
- 렌더 payload는 파일 쓰기 전에 모두 생성하므로 렌더 실패 시 DB 수정과 이전 artifact가 유지된다.

## 검증

- 정적 검사와 unit/integration 전체 결과는 PR 본문에 기록한다.
- 통합 테스트에서 revision 일치, stale summary 차단, 조건부 재요약, 재전사 미실행, 동시 수정 거부를
  확인한다.

## 비범위

- 키보드 접근성 및 브라우저 E2E는 R5-09에서 다룬다.
- 사용자 힌트 기반 STT 재수행은 R5-10 이후에서 다룬다.
