# R6-03 화자 후보 점수와 보수적 자동 확정

## 작업 관계

- 작업 브랜치: `feature/r6-03-speaker-auto-match`
- 기준 브랜치: `main`
- 후속 작업: `feature/r6-04-speaker-match-ui`
- 병합 순서: R6-03을 먼저 병합한 뒤 R6-04를 `main` 기준으로 재배치한다.

## 구현 결과

- SQLite schema를 v10으로 올리고 녹음 화자별 평가 결과, person별 후보 순위와 점수, 사용자가
  자동 연결을 바꾼 거부 이력을 보존한다. 새 평가의 결과와 후보는 한 transaction에서 교체하며,
  거부 이력은 재전사로 화자 원장을 교체해도 유지한다.
- 수동 확정된 대표 clip만 기존 embedding/profile 학습 자료로 사용한다. 미확정 화자는 대표
  clip이 두 개 이상이고 eligible profile이 있을 때만 모델을 호출하며, 같은 실제 model
  fingerprint의 profile member embedding과 모든 교차 cosine similarity를 계산한 중앙값을
  `0.0~1.0`으로 제한해 후보 점수로 저장한다.
- 후보는 점수 내림차순, person ID 오름차순으로 고정한다. best/second-best와 margin을 저장하고,
  후보 한 명의 second-best는 `0.0`으로 처리한다.
- 자동 확정은 기본 비활성화다. 활성화하려면 threshold와 margin을 모두 `0.0~1.0` 범위로
  지정해야 하며, 절대 점수·margin·같은 녹음의 중복 person·동일 person을 두 미확정 화자가
  경쟁하는 경우·과거 거부 이력을 모두 보수적으로 검사한다. 경쟁 점수가 같으면 어느 화자도
  자동 연결하지 않는다.
- 자동 연결은 후보 결과, `recording_speakers`, 관련 `segments`, 녹음 revision과
  `needs_speaker_review`, audit event, revision별 render job을 한 transaction으로 반영한다.
  자동 연결 자료는 profile에 들어가지 않으며 사용자가 수동으로 확인한 뒤에만 학습 자료가 된다.
- 오래된 finalize job은 시작 시점과 저장 transaction에서 revision을 확인해 새 배정이나 후보
  결과를 덮어쓰지 않는다. embedding 및 자동 확정 설정 전체를 finalize job fingerprint에 넣어
  설정이 다른 실행을 같은 작업으로 취급하지 않는다.
- 최초 전사와 재전사 모두 대표 clip 생성 후 `finalize_speakers`를 먼저 등록하고, 성공한 최신
  revision만 classification으로 이어진다. clip이나 profile이 부족하면 모델을 로드하지 않고
  `insufficient_clips`, `no_profiles`, `insufficient_profiles` 판정만 저장한다.
- 녹음 상세 API에 nullable `match`와 고정 판정 코드, best/second/margin, 입력 revision, 후보의
  person ID·표시 이름·순위·점수·거부 여부를 추가했다. OpenAPI snapshot과 생성 TypeScript 타입을
  함께 갱신했다.
- `.env.example`, Compose 전달 설정과 README에 기본 비활성화 계약을 반영했다. R6-05 실제 분포
  평가 전에는 임의 threshold 기본값을 제공하지 않는다.

## 자동 검증

- `make check-format`: 통과
- `make lint`: 통과
- `make typecheck`: 통과
- `make api-schema-check`: 통과
- `make test-unit`: 통과, 317개
- `make test-integration`: 통과, 19개
- `make test-frontend`: 통과, 18개
- `docker compose config`: 통과
- `make compose-smoke`: 통과. fake pipeline의 최초 전사·수동 화자 수정·재전사에서
  `finalize_speakers`를 포함한 8개 job 성공, 브라우저 흐름과 worker 재시작 후 결과 보존을
  확인했다.
- 추가 회귀: v9→v10 데이터 보존, 설정 경계, exact fingerprint 격리, 수동 자료만 profile에
  포함, 중앙값과 고정 순위, 낮은 점수와 margin 부족, clip/profile 부족 시 모델 미호출, 후보-only
  기본 동작, 기존·경쟁 person 중복 방지, 동점 보수 처리, 거부 후보 제외, 자동 배정 transaction,
  audit/render 등록, stale revision, 재실행 멱등성, 재전사 후 거부 이력 보존을 확인했다.

## 실제 NVIDIA/GPU 검증 상태

- 이 변경은 실제 `pyannote/embedding` worker 실행 순서와 후보 계산 경로에 영향을 주므로 실제
  NVIDIA/GPU 애플리케이션 검증이 필요하다.
- 현재 개발 환경은 NVIDIA runtime이 없는 Docker Desktop이며, 현재 세션에는 운영 서버 접속
  대상과 인증 정보가 제공되지 않아 `compose.yaml`과 `compose.gpu.yaml`을 사용한 비공개 표본
  검증을 실행하지 못했다. 샌드박스의 GPU 결과로 드라이버 가용성을 판단하지 않았다.
- 운영 서버에서 같은 fingerprint의 eligible profile 생성, 별도 미확정 화자의 실제
  `pyannote/embedding` 후보 점수·순위 저장, 기본 flag 비활성화 시 연결 불변을 확인해야 한다.
  모델 사용 승인이 403이면 해당 차단을 그대로 기록한다. 이 검증은 R6-05 착수 전 필수
  선행조건으로 남긴다.

## 비범위

- R6-04 후보 근거 및 검토 UI
- R6-05 threshold·margin 보정과 R6-06 고정 회귀 평가
- 외부 vector DB, 별도 식별 서비스 또는 새로운 상태 관리 패키지
