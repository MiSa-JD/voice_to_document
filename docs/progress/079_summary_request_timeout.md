# 요약 요청 timeout 설정

- `SUMMARY_REQUEST_TIMEOUT_SECONDS` 기본 300초를 추가했다. 유한한 양수만 허용한다.
- worker와 실제 평가 어댑터에 전달하고 Compose 공통 환경, 공개 설정, README에 반영했다.
- 각 네트워크 요청에 적용되며 전체 작업 제한이 아니다. 내용 fingerprint에는 포함하지 않는다.
- 관련 config/worker/adapter/evaluation 단위 테스트 60개 통과.
- 실제 장문 API와 최종 공통 검사는 081 문서에 기록한다. R8 BLOCKED, R9 NOT STARTED 유지.
- 요약 경로는 GPU를 사용하거나 런타임에 영향을 주지 않아 실제 NVIDIA/GPU 검증은 불필요하다.
