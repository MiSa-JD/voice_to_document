# R6-04 화자 후보 근거 및 자동 연결 검토 UI

## 작업 관계

- 작업 브랜치: `feature/r6-04-speaker-match-ui`
- 기준 브랜치: `feature/r6-03-speaker-auto-match` (PR #36)
- 병합 순서: PR #36을 먼저 병합한 뒤 이 PR을 `main` 기준으로 재배치하고 다시 검증한다.

## 구현 결과

- 화자 검토 화면 상단에 “유사도 기반 편의 기능이며 신원 인증이 아님”을 상시 표시하고 대표
  음성을 직접 확인하도록 안내한다.
- 각 화자 카드에 자동 확정·수동 확정·미확정 출처를 색상과 별개의 텍스트로 표시한다. 자동
  확정은 저장된 유사도도 함께 보여 준다.
- R6-03 API의 1순위 후보 이름과 점수, 2순위 점수, 1·2위 margin을 구조화된 설명 목록으로
  표시한다. 후보가 한 명뿐인 경우 2순위가 없다는 점을 함께 알린다.
- 대표 clip 부족, 같은 model fingerprint의 profile 없음, 수동 표본 부족, 자동 확정 비활성화,
  낮은 절대 점수, margin 부족, 같은 녹음의 중복 person, 과거 거부, 자동 확정 완료의 모든 판정
  코드를 한국어 문장으로 설명한다.
- 후보 배열을 순위·이름·점수·과거 거부 여부와 함께 보여 주고 각 후보를 native button으로 수동
  확정할 수 있게 했다. 저장은 기존 revision 보호 PUT API를 그대로 사용하므로 자동 연결을 다른
  인물 또는 `알 수 없음`으로 바꿀 때 R6-03 거부 이력이 기록된다.
- match 결과가 아직 없는 상태와 대표 clip 생성 대기를 별도 `role=status` 문구로 구분한다. 기존
  loading, 일반 오류, 저장 중, 409 revision 충돌, 최신 내용 재로딩 흐름을 유지한다.
- 후보 버튼과 기존 select는 키보드로 조작할 수 있고 전역 `focus-visible` 표시를 사용한다. 화자별
  근거를 이름이 있는 region으로 제공하고 저장 상태·오류의 screen reader 알림을 유지한다.
- 새 상태 관리 패키지나 디자인 시스템 없이 기존 React state, API client와 CSS 변수를 재사용했다.
- Compose smoke가 실제 저장소 E2E 표준 진입점을 사용하도록 첫 브라우저 실행을
  `make test-e2e`로 통일했다.

## 검증

- `make check-format`: 통과
- `make lint`: 통과
- `make typecheck`: 통과
- `make api-schema-check`: 통과
- `make test-unit`: 통과, 317개
- `make test-integration`: 통과, 19개
- `make test-frontend`: 통과, 21개
- `docker compose config`: 통과
- `make test-e2e`: Compose smoke의 실제 서비스 stack에서 통과, 3개
- `make compose-smoke`: 통과. 전체 E2E 3개와 worker 재시작 보존 E2E 1개를 확인했다.
- UI 회귀에서 자동·수동·미확정 출처, best/second/margin, 모든 판정 이유, 상시 고지, 후보 버튼
  수동 확정, 자동 연결의 `알 수 없음` 변경, 후보 pending, loading/error, 저장 중, 409 충돌,
  전체·개별·일괄 화자 수정과 키보드 focus 흐름을 확인했다.

## GPU 검증 판단

- R6-04 고유 변경은 React 표시·입력과 브라우저 검증에 한정되며 GPU runtime을 사용하거나
  변경하지 않으므로 별도 실제 NVIDIA/GPU 재검증은 불필요하다.
- 선행 PR #36의 실제 GPU 애플리케이션 검증 미완료 조건은 그대로 유지하며 R6-05 착수 전에
  운영 서버에서 완료해야 한다.

## 비범위

- R6-03 후보 점수·자동 확정 알고리즘 변경
- R6-05 threshold·margin 보정과 R6-06 고정 회귀 평가
- 새로운 상태 관리 패키지 또는 디자인 시스템 도입
