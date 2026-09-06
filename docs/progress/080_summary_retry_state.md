# 요약 재시도 상태 처리

- 요약 timeout·일시 오류·artifact I/O 실패 시 recording은 SUMMARIZING으로 유지한다.
- 기존 최대 3회, 2·4초 재예약 간격을 유지한다.
- 최종 실패 시 jobs 갱신과 recordings 실패를 동일 트랜잭션으로 처리한다.
  summarize 종류, 현재 revision, SUMMARIZING 상태를 확인한다.
- worker 경유 회귀 테스트 포함 summary requests 통합 테스트 13개 통과.
  세 번째 성공 시 JSON/Markdown 각 한 건, 재시도 소진, 영구 실패,
  처리 중 revision 변경 보호와 수동 재요청 복구를 검증했다. mypy/ruff 통과.
- 운영 DB 일괄 변경은 하지 않는다. R8 BLOCKED, R9 NOT STARTED 유지.
- GPU 실행 경로와 런타임에 영향이 없어 실제 NVIDIA/GPU 검증은 불필요하다.
