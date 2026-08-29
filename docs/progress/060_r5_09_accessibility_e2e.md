# R5-09 접근성·브라우저 E2E

## 구현

- `window.prompt`를 제거하고 이름 label, 입력 설명, inline 오류, 취소/완료 초점 복귀가 있는 새 인물
  form을 화자 연결과 발화 일괄 변경 흐름에 추가했다.
- 전체 오디오, 대표 클립, 화자 선택, timestamp 재생에 문맥을 포함한 접근 가능한 이름을 제공했다.
- 선택 여부는 `aria-pressed`와 “선택됨/선택 안 됨” 텍스트로, 저장 상태는 live status로 전달한다.
- DOM 순서를 선택 → 새 인물 form → 확인 → 저장 순서로 유지해 키보드 focus 순서를 고정했다.
- Playwright pipeline 흐름에 대표 클립(고정 fixture에 적격 clip이 없으면 전체 오디오) 키보드 재생,
  새 인물 입력, 발화 선택, 확인, 저장, render 완료 확인을 추가했다.

## 검증

- frontend component test에서 form 자동 focus, 설명 연결, validation 오류, 취소 후 focus 복귀를 확인한다.
- browser E2E와 compose smoke 결과는 PR 본문에 기록한다.

## 비범위

- STT 재수행 API 계약과 UI는 R5-10/R5-11에서 다룬다.
