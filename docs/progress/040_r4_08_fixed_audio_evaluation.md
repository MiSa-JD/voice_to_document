# R4-08 — 고정 음성 실제 모델 평가

- 기록 번호: 040
- 상태: 완료
- 관련 로드맵: R4-08, R4 종료 게이트 M2
- 작업 브랜치: `feature/r4-08-fixed-audio-evaluation`
- 완료 시각: 2026-08-27T02:17:05Z

## 작업한 내용

- Git에서 제외된 `MODEL_EVAL_ROOT`의 단일 화자, 다중 화자, 저발화·무음 포함 m4a 세 개를
  실제 `RealSpeechPipelineHandler`의 ingest → FFmpeg → WhisperX → alignment → pyannote → 저장
  경로로 처리하는 `make model-eval`을 추가했다.
- batch size `4,8,16`을 오름차순 평가하고, 전체 GPU 메모리 90% 이하인 완료 후보 중 최속 시간의
  10% 안에 드는 가장 작은 값을 선택한다. OOM 후보가 나오면 더 큰 후보를 실행하지 않는다.
- 후보별 DB와 artifact는 임시 디렉터리에 만들고 종료 시 제거한다. 공개 JSON에는 장비·모델
  fingerprint, 역할, 길이, segment·화자·배정 상태 수, 처리 시간과 GPU 메모리만 포함한다.
  transcript, 녹음 경로, 파일명, token과 원본 예외 메시지는 출력하지 않는다.
- 한국어 WhisperX alignment가 NLTK tokenizer 자료를 내려받을 수 있도록 모델 cache와 분리된
  전용 `NLTK_CACHE_ROOT`를 추가하고 host 권한을 `0700`으로 고정했다.
- WhisperX가 입력 전사 segment보다 많은 문장 segment를 반환하는 실제 동작을 확인했다.
  각 분할 segment가 자체 시간과 text를 갖는 경우 모두 정규화하되, 누락 값을 원본 segment에서
  보완하던 기존 계약은 출력 수가 입력 이하일 때 그대로 유지했다.

## 실제 평가 결과

- 장비: NVIDIA GeForce RTX 3060 12GB, driver 535.309.01, CUDA runtime 12.8
- 패키지: Torch 2.8.0+cu128, WhisperX 3.8.6, pyannote.audio 4.0.7
- batch size `4`: 완료, 총 68.888초, 최대 GPU 메모리 7,638 MiB
  - 단일 화자 역할: 195,730 ms, 36 segments, 2 speakers, 31.361초
  - 다중 화자 역할: 502,761 ms, 144 segments, 2 speakers, 35.562초
  - 저발화·무음 역할: 23,466 ms, 1 segment, 1 speaker, 1.867초
- batch size `8`: `MODEL_OOM`
- batch size `16`: 더 작은 후보의 OOM 이후 안전 규칙에 따라 미실행
- 선택값: `4`; `.env.example`과 runtime 기본값을 그대로 유지한다.

모든 완료 표본은 segment 시간 오름차순, 양수 길이, 오디오 범위 안의 시간 값과 화자 구간 생성
조건을 만족했다. 단일 화자 역할이 두 화자로 과분할된 결과는 숨기지 않고 품질 관찰값으로 남긴다.
R4-08은 로드맵대로 문장 완전 일치보다 시간 불변식과 다중 화자 구간 생성을 우선하며, 정확한 화자
수 교정은 R5 수동 검토와 R10 품질 평가에서 다룬다.

## 평가 중 발견하고 해결한 문제

- 컨테이너 사용자 홈과 group-writable 모델 cache에서는 NLTK 3.10 보안 검사로 한국어 tokenizer
  다운로드가 거부됐다. 전용 `0700` cache mount로 권한과 영속성을 분리했다.
- 실제 한국어 alignment는 7개 전사 segment를 36개 문장 segment로 나눴다. 정상적인 문장 분할을
  잘못된 응답으로 거부하던 adapter를 실제 출력 계약에 맞추고 회귀 테스트를 추가했다.
- 전체 backend 회귀에서 SQLite WAL 초기화 경쟁이 반복 재현돼 별도 작업 단위
  [039](039_sqlite_wal_initialization_race.md)로 수정·커밋한 뒤 이 브랜치에 포함했다.

## 검증 상태

- 비공개 실제 m4a `make model-eval`: 통과, batch size `4` 선택
- backend unit/integration: 218개 통과
- model eval 정책·개인정보 출력과 WhisperX 문장 분할 alignment 회귀 테스트: 포함해 통과
- frontend Vitest: 9개 통과
- Ruff format/lint: 59개 backend 파일 통과
- mypy strict: 58개 source 파일 통과
- OpenAPI snapshot, 생성 TypeScript 타입, Prettier, ESLint, TypeScript strict: 통과
- 기본 fake Compose api/worker/web health: 통과
- Playwright readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- GPU Compose profile 병합과 `git diff --check`: 통과

FastAPI TestClient와 SQLite 동시성 테스트는 샌드박스 밖에서 실행했다. 기존 httpx2 전환 경고
1건은 테스트 실패나 현재 API runtime 오류가 아니다.

## 알려진 조건과 다음 작업

- 모델 평가에는 Linux NVIDIA GPU, 유효한 `HF_TOKEN`, 사전 승인한 pyannote 모델 접근과 비공개
  표본 세 개가 필요하며 일반 CI와 기본 Compose에서는 실행하지 않는다.
- M2 검증 작업에서 전체 회귀 결과를 확정하고 R4 종료 게이트와 진행 현황 표를 갱신한다.
