# 요약 공급자 ID 참조와 원본 시간 연결

작성일: 2026-09-08. R8 운영 hotfix의 첫 구현 단위.

## 목적과 관계

086 계획의 확인된 시간 생성 오류를 제거한다. 최신 main(c346b02)에 진단 PR #53이
병합되어 있으며 열린 PR은 없음을 확인했다.
독립 hotfix 브랜치는 `fix/summary-evidence-timestamps → main`이다.
한 오류에 대한 응집된 PR 안에서 참조 계약 → fingerprint/통합 → 전체 검증/인계를
각각 커밋한다. 병합은 사용자 요청 이후 수행한다.
기존 미추적 086 계획 파일은 내용을 바꾸지 않고 함께 보존한다.

## 변경

- 공급자 전용 StrictModel이 다섯 template와 회의 action_items의 ID·quote를 검증한다.
- 검증된 fact 노드만 같은 호출의 transcript UUID에 연결해 원본 시간을 채운다.
- 전체 요약, chunk 사실 추출, 최종 합성에 적용한다. 합성 입력의 추출 사실에서도 시간을 제외한다.
- 최종 CategorySummary/Evidence 및 공통 시간·인용문·chunk 검증은 유지한다.
- 공급자가 반환한 시간 및 추가 필드는 거절한다. chunk 최상위 추가 필드도 거절한다.
- UUID 표기 차이를 정규화하며 입력 transcript와 공유 어댑터 상태를 변경하지 않는다.
- 실제 응답 위치의 진단, 교정 1회, 안전한 오류 메시지를 유지한다.

## 검증

기존 .venv에서 다음을 실행했다.

- `pytest backend/tests/unit/test_openai_summary.py backend/tests/unit/test_summary_schema.py backend/tests/integration/test_summary_requests.py -q`: 111 통과.
- `mypy`: 96개 파일 통과.
- 동일/역전 시간의 기존 value_error 재현, 다섯 template의 모든 근거 위치 및 두 segment 연결,
  잘못된 UUID·null·누락·시간/추가 필드 거절, JSON formatter 경로와 비밀값 비노출을 확인했다.
- 한 segment를 여러 slice로 나눠도 원본 시간을 사용하고, quote는 원본 segment 기준으로 검증한다.
- 기존 unknown_segment/quote_mismatch/outside_chunk, 교정 성공·실패, 동시 호출 회귀 통과.

fingerprint 버전·평가 기대값과 구버전 작업 호환성은 다음 커밋에서 검증한다.
전체 기본 검사 및 CI는 마지막 단위에서 기록한다.
실제 NVIDIA/GPU 검증은 불필요하다. 변경 경로는 호스팅 요약 API의 CPU 처리이며
GPU 실행·의존성·장치 선택·컨테이너 런타임을 사용하거나 변경하지 않는다.
운영 서버 배포와 유료 재요청은 실행하지 않았다. R8 BLOCKED를 유지한다.
