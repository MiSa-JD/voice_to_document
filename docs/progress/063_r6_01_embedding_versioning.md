# R6-01 — embedding 생성·버전 관리

- 기록 번호: 063
- 상태: 구현 완료, 실제 gated 모델 접근 승인 대기
- 관련 로드맵: R6-01
- 작업 브랜치: `feature/r6-01-embedding-versioning`
- 기준 브랜치: `main`
- 완료일: 2026-08-30

## 작업한 내용

- `sqlite-vec 0.1.9`를 고정하고 schema v8에 512차원 float32/cosine `vec0` 저장소와 논리 UUID를
  정수 vector row에 연결하는 원장을 추가했다. 기존 `speaker_embeddings`를 판정 metadata의 원장으로
  유지하며 벡터 본문과 같은 SQLite transaction에서 등록한다.
- 수동 확정된 녹음 화자의 최신 대표 clip 중 현재 segment도 같은 인물로 수동 확정된 깨끗한
  source만 embedding 대상으로 사용한다. fake adapter는 CI에서 결정적으로 동작하고 실제 adapter는
  `pyannote/embedding`의 whole-window inference를 사용한다.
- 벡터는 512차원, 유한값, 양의 norm을 검증하고 L2 정규화한다. fingerprint에는 모델 이름과 요청
  revision, 실제 weight state SHA-256, pyannote.audio 버전, mono PCM 16 kHz 전처리 버전과 차원을
  포함하므로 호환되지 않는 결과를 같은 버전으로 취급하지 않는다.
- 기존에 schema에 예약돼 있던 `finalize_speakers` job을 활성화했다. 화자 전체·개별·일괄 수정은
  영향받은 활성 embedding을 즉시 무효화하고 벡터 본문을 제거한 뒤, 최신 revision과 설정
  fingerprint로 job을 멱등 등록한다.
- worker는 계산 뒤 현재 person/segment/clip 연결을 다시 확인해 오래된 결과 등록을 막는다. 모델
  접근 거부와 OOM은 자동 재시도로 해결할 수 없는 오류로, 일시적 다운로드·clip I/O·inference
  실패는 제한 재시도 오류로 구분한다.
- `SPEAKER_EMBEDDING_MODEL`, `SPEAKER_EMBEDDING_MODEL_REVISION`,
  `SPEAKER_EMBEDDING_DEVICE` 설정과 운영 문서를 추가했다. 토큰, 원본 경로, 음성 및 transcript
  내용은 로그와 진행 문서에 기록하지 않는다.

## 자동 검증 결과

- Ruff format/lint, mypy strict, Prettier, ESLint, TypeScript strict: 통과
- OpenAPI snapshot과 생성 TypeScript type drift: 통과
- backend unit: 303개 통과
- backend integration: 19개 통과
- frontend unit: 18개 통과
- Compose/Playwright 스모크: `finalize_speakers`를 포함한 6개 job 성공과 worker 재시작 후 결과
  보존 통과
- 신규 검증: migration/extension 로드, 512차원과 cosine, 정규화, 멱등 vector identity, model
  fingerprint 분리, 수동·현재 source 제한, 무효화 metadata 보존, 잘못된 벡터 거부, gated 모델
  접근 오류 분류

## GPU와 실제 모델 검증

- 샌드박스 밖 host와 Docker에서 RTX 3060 12GB, driver 535.309.01 접근을 각각 확인했다.
- 격리된 Compose에서 실제 worker의 STT, alignment, diarization, 대표 clip 생성, 수동 화자 연결과
  `finalize_speakers` 등록까지 확인했다.
- 현재 `HF_TOKEN`은 `pyannote/speaker-diarization-community-1`에는 접근 가능하지만 별도 gated
  모델인 `pyannote/embedding` 사용 승인이 없어 실제 embedding download가 403으로 거부됐다.
  애플리케이션은 이를 `MODEL_ACCESS_DENIED` 최종 실패로 분류했으며 무의미한 재시도를 하지 않는다.
  해당 모델 사용 조건 승인 후 같은 검증을 다시 실행해야 한다.
- 검증용 Compose container/network와 생성한 임시 데이터 루트는 종료 후 삭제했다.

## 비범위와 다음 작업

- 인물별 profile 집계와 sample 부족 판정은 R6-02에서 구현한다.
- 후보 점수, threshold/margin, 자동 확정과 후보 UI는 R6-03 이후 범위다.
- 실제 transcript, 힌트, 원본 파일명·절대 경로와 credential은 테스트 출력과 이 문서에 포함하지
  않았다.
