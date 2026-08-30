# R6-03 실제 GPU 검증

- 기록 번호: 067
- 상태: 모델 접근 권한 차단
- 관련 로드맵: R6-03, R6-05 선행 검증
- 작업 브랜치: `docs/r6-03-gpu-verification`
- 검증일: 2026-08-30

## 검증 범위

- 이미 병합된 R6-03의 `pyannote/embedding` 화자 embedding 및 후보 계산 경로만 검증했다.
- 호스트 NVIDIA 접근, Docker GPU runtime, `compose.yaml`과 `compose.gpu.yaml`을 병합한 실제
  worker 경로를 순서대로 확인했다.
- 기존 비공개 단일 화자 표본을 원본 수정 없이 시간상 분리해 수동 확정 profile용 clip 두 개와
  별도 미확정 query용 clip 두 개로 사용했다. 검증용 Compose project, SQLite DB와 임시 clip은
  기존 runtime 데이터와 분리했고 종료 후 제거했다. 기존 모델 cache는 유지했다.
- transcript, 비공개 원본 경로와 자격 증명은 로그와 이 문서에 남기지 않았다.

## 실제 NVIDIA/GPU 결과

- 호스트 `nvidia-smi`: 통과
  - GPU: NVIDIA GeForce RTX 3060 12GB
  - driver: 535.309.01
- Docker `--gpus all`: 통과
  - `nvidia/cuda:12.8.0-base-ubuntu22.04` 컨테이너에서 같은 GPU와 driver를 확인했다.
- 실제 Compose worker: 모델 접근 권한 차단
  - `SPEECH_MODE=real`, `DOCUMENT_MODE=fake`, 기본값
    `SPEAKER_AUTO_MATCH_ENABLED=false`로 격리된 worker를 실행했다.
  - 수동 확정 화자의 첫 `finalize_speakers` 작업은 실제 `pyannote/embedding` 모델 load 경로에
    진입했지만 모델 허브가 접근을 거부해 `MODEL_ACCESS_DENIED`로 실패했다.
  - query 작업은 선행 embedding/profile이 없으므로 모델을 호출하지 않고 `no_profiles` 판정을
    저장했다. 이는 후보 계산 성공이 아니다.
  - query의 `recording_speakers.person_id`는 `NULL`, `speaker_source`는 `unresolved`, 녹음과 화자
    revision은 모두 `1`로 유지됐다. 기본 비활성화 상태에서 자동 연결이나 revision 변경은 없었다.

계획의 fail-closed 조건에 따라 이 실행을 실제 embedding 검증 성공으로 처리하지 않는다. 모델
접근 승인을 복구한 뒤 아래 항목을 다시 확인해야 R6-03 실제 GPU 검증이 완료된다.

- 같은 실제 model fingerprint의 활성 embedding 두 개 이상과 eligible profile 생성
- 별도 미확정 query의 후보 점수와 1순위 rank 저장
- 후보와 profile의 model fingerprint 일치
- 기본 flag 비활성화 상태의 `auto_disabled` 판정과 화자 연결·revision 불변

## 일반 회귀 검사

- `make check-format`: 통과, Ruff 83개 파일과 Prettier
- `make lint`: 통과
- `make typecheck`: 통과, mypy strict 82개 source 파일과 TypeScript
- `make api-schema-check`: 통과
- `make test-unit`: 통과, 317개
- `make test-integration`: 통과, 19개
- `make test-frontend`: 통과, 21개
- `docker compose config --quiet`: 통과
- `git diff --check`: 통과

uv cache가 샌드박스에서 읽기 전용이어서 첫 정적 검사 실행은 환경 오류로 종료됐다. 저장소 지침에
따라 같은 검사를 샌드박스 밖에서 다시 실행해 모두 통과했다. backend 테스트의 기존
Starlette/httpx2 전환 경고 1건은 실패가 아니다.

## 변경 및 비범위

- 공개 API, DB schema, 환경 변수와 기본값을 변경하지 않았다. 이 PR의 최종 변경은 검증 결과
  문서뿐이다.
- R6-05 threshold·margin 보정, R6-06 고정 회귀 평가와 자동 확정 활성화는 수행하지 않았다.
- 모델 허브 권한 변경이나 credential 갱신은 이 저장소 문서 PR의 범위가 아니다.
- 이 작업은 현재 PR stack과 무관한 독립 문서 PR이며 base는 `main`, 선행·후속 PR은 없다.
