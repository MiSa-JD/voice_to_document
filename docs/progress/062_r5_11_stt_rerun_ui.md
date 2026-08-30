# R5-11 STT 재수행 확인·진행 UI와 M3 검증

## 구현

- 녹음 상세에 지원 언어, 내용 설명, 전문용어 입력과 정확도 비보장 안내를 추가했다.
- 별도 확인 단계에서 transcript 교체, 화자/대표 클립 재검토, 분류/요약 stale 영향, 실패 보존을
  안내하며 확인 전에는 POST 요청을 보내지 않는다.
- 제출 중 입력을 잠그고 latest API polling으로 대기, 진행, 자동 재시도 대기, 실패, 완료를 구분한다.
- 실패 시 기존 transcript를 계속 표시하고 재시도 진입점을 제공한다. 성공 시 이전/새 언어, 발화 수,
  미확정 화자 수와 화자 재검토 링크를 표시한다.
- fake compose browser E2E에 화자 수정 이후 언어/힌트 재전사, 원자 전환, 비교 UI, worker 재시작 보존을
  추가했다.

## R5 종료 게이트

- 화자 생성·전체/개별/일괄 수정·확인·revision 충돌·재렌더 흐름을 unit/integration/browser E2E로
  확인했다.
- 재전사 실패 보존과 성공 후 stale/재검토 전환, history, hint 삭제를 integration test로 확인했다.
- 키보드 focus와 접근 가능한 이름을 component test 및 browser E2E로 확인했다.
- 전체 검증 및 실제 GPU 표본 결과는 PR 본문에 기록하며 비공개 transcript, 힌트, 원본 경로는
  기록하지 않는다.
- 샌드박스 밖 host와 Docker에서 RTX 3060을 확인했고, 실제 worker의 힌트 없음 처리와 힌트 적용
  재전사가 모두 성공했다. 재전사 revision 전환, history 보존, 실패 job 0개를 확인했다.

## 후속

- R6의 보수적인 화자 자동 식별은 R5에서 수동 확정된 표본을 입력으로 사용한다.
