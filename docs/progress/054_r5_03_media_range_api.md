# R5-03 — Media Range API

- 기록 번호: 054
- 상태: 완료
- 관련 로드맵: R5-03
- 작업 브랜치: `feature/r5-03-media-range-api`
- 기준 브랜치: `feature/r5-02-speaker-clips`
- 선행 PR: #17
- 완료일: 2026-08-29

## 작업한 내용

- 녹음 등록 트랜잭션에 `recording_audio` artifact 등록을 포함했다. content hash 중복으로 같은
  녹음의 source 위치가 갱신되면 상대 경로만 갱신하고 기존 recording 및 artifact ID는 유지한다.
- worker discovery가 중첩된 inbox 경로도 설정된 `RECORDING_INPUT_DIR` 기준 상대 경로로 저장한다.
  configured root를 벗어나는 source는 등록 전에 거부한다.
- `GET /api/media/{artifact_id}`를 추가했다. `recording_audio`는 recording input root에서,
  `speaker_clip:*`은 `speaker_clips` 원장에 등록된 경우에만 speaker root에서 제공한다. transcript,
  summary와 원장에 없는 artifact는 존재 여부를 구분하지 않는 404로 처리한다.
- Range가 없으면 200과 전체 파일을, 단일 `start-end`, `start-`, `-suffix` byte range이면 206과
  해당 범위만 64 KiB 단위로 stream한다. 끝 위치가 파일보다 크면 실제 마지막 byte로 제한한다.
- malformed, 다중, 역방향, 빈 suffix와 파일 범위 밖 요청은 공통 오류 본문, `416`,
  `Content-Range: bytes */<size>`로 응답한다.
- 성공 응답에는 `Accept-Ranges`, 정확한 `Content-Length`, 206의 `Content-Range`와 `.m4a`의
  `audio/mp4`, 대표 WAV의 `audio/wav` MIME type을 제공한다.
- artifact 상대 경로는 설정 root에서 strict resolve하고 regular file만 연다. traversal, 누락 파일,
  symlink root 탈출과 0 byte 파일은 모두 404로 숨긴다.
- 녹음 상세 API의 artifact 응답에서 내부 `relative_path`를 제거했다. media 응답과 오류에는 절대
  경로, artifact 상대 경로, 원본 파일명 또는 OS 오류 내용을 포함하지 않는다.
- OpenAPI snapshot과 생성 TypeScript 타입에 media endpoint, Range header, 404/416 계약을
  반영했다.

## 자동 검증 결과

- Ruff format/lint와 `git diff --check`: 통과
- mypy strict: 75개 source 파일 통과
- Prettier, ESLint, TypeScript strict: 통과
- OpenAPI snapshot과 생성 TypeScript 타입 drift: 통과
- backend unit: 288개 통과
  - 원본 artifact 동시 등록, transaction rollback, 중복 source 위치 갱신 및 identity 보존
  - 전체/부분/open-ended/suffix/끝 초과 range와 byte 본문·헤더
  - malformed·다중·역방향·unsatisfiable range의 416 계약
  - 원본/대표 클립 MIME, 원장에 없는 artifact, 누락 파일, traversal, symlink 탈출
  - 응답과 공통 오류의 내부 경로 비노출
- backend integration: 15개 통과
- frontend unit: 9개 통과
- Docker Compose browser smoke: pipeline/health 2개와 worker 재시작 보존 1개 통과

## 비범위와 다음 작업

- person 생성·수정과 화자/segment 수동 연결은 R5-04에서 구현한다.
- media authorization은 현재 local-first 단일 사용자 배포의 artifact allowlist와 root 검증을
  의미한다. 사용자 계정·세션 권한 모델은 현재 범위에 없다.
- 이번 변경은 GPU 모델을 다시 실행하지 않으므로 GPU 검증은 수행하지 않았다.
- 비공개 transcript 본문, 원본 절대 경로와 credential은 테스트 출력과 이 문서에 기록하지 않았다.
