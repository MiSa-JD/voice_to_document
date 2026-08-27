# R7-03 긴 transcript 처리

## 상태

- backend-only 선행 트랙의 P3 완료

## 변경

- 설정된 context 문자 한도 이내에서는 정규화 transcript 전체를 분류 adapter에 한 번 전달한다.
- 한도 초과 시에만 segment slice별 부분 주제를 추출하고, transcript 식별 메타데이터와 전체 주제를
  사용해 최종 분류한다.
- 긴 단일 segment도 앞부분 절단 없이 여러 slice로 처리한다.
- 모든 slice가 원본 segment ID, 시작·종료 millisecond, 임시 화자 ID, part index를 보존한다.
- strategy와 context 한도를 model fingerprint에 포함한다.

## 검증

- 경계값에서 전체 transcript 경로가 한 번만 호출되는지 확인했다.
- 초과 입력의 모든 문자가 순서대로 보존되고 최종 분류가 한 번만 수행되는지 확인했다.
- transcript 본문이나 입력 절대 경로를 로그와 이 문서에 기록하지 않았다.
