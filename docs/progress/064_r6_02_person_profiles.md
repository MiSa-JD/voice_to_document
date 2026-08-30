# R6-02 — 인물 프로필 계산

- 기록 번호: 064
- 상태: 완료
- 관련 로드맵: R6-02
- 작업 브랜치: `feature/r6-02-person-profiles`
- 기준 브랜치: `feature/r6-01-embedding-versioning`
- 선행 PR: #32
- 완료일: 2026-08-30

## 작업한 내용

- SQLite schema를 v9로 올리고 person/model fingerprint별 `speaker_profiles`와 profile에 사용된
  정확한 `speaker_profile_members` 원장을 추가했다. 표시 이름이 아니라 person ID로 구분하며 서로
  다른 model fingerprint의 sample을 섞지 않는다.
- 현재도 같은 인물로 수동 확정된 녹음 화자와 segment에 연결된 활성 embedding만 집계한다.
  연결 취소, 다른 인물로 변경, 대표 clip source segment의 개별 수정과 무효화된 embedding은 profile
  입력에서 제외한다.
- 각 sample을 정규화된 float32 벡터로 읽고 산술 평균을 다시 L2 정규화한 centroid를 embedded
  VDB에 저장한다. centroid는 R6-03의 빠른 후보 검색에 사용하고 member 목록은 median 기반 재점수와
  근거 확인에 사용할 수 있게 보존한다.
- 같은 fingerprint의 유효 sample이 2개 이상일 때만 `eligible` profile과 vector를 만든다. 0~1개면
  sample/recording 수를 기록하되 vector가 없는 `insufficient` 상태로 두어 자동 확정 후보가 되지
  않게 한다.
- 화자 수정 transaction은 영향받은 기존 profile vector와 membership을 즉시 보수적으로
  비활성화한다. 뒤이어 같은 `finalize_speakers` job이 이전·새 인물의 profile을 현재 sample로 멱등
  재계산하므로 중단 중 오래된 profile이 후보로 사용되지 않는다.
- profile과 sample vector는 같은 `speaker_vector_keys`/`speaker_vectors` 저장소를 공유하며 논리
  vector key로 종류를 구분한다. metadata와 vector 갱신은 한 SQLite transaction에서 완료한다.

## 자동 검증 결과

- Ruff format/lint, mypy strict, Prettier, ESLint, TypeScript strict: 최종 전체 검증 통과
- OpenAPI snapshot과 생성 TypeScript type drift: 통과
- backend unit: 305개 통과
- backend integration: 19개 통과
- frontend unit: 18개 통과
- 신규 검증: v8→v9 migration, fingerprint별 profile 격리, 두 sample eligibility, 한 sample
  insufficient, 정규화 centroid, 정확한 membership, 재실행 멱등성, 연결 취소 즉시 비활성화와 남은
  sample 재집계

## 비범위와 다음 작업

- best/second-best 점수, 절대 threshold와 margin, 같은 녹음 중복 인물 방지 및 feature flag는
  R6-03에서 구현한다.
- 후보 근거와 자동·수동 출처 UI는 R6-04 범위다.
- 실제 threshold는 R6-05의 같은 사람·다른 사람·애매한 표본 평가 전에는 확정하지 않는다.
- 비공개 음성, transcript, 원본 경로와 credential은 테스트 로그와 이 문서에 포함하지 않았다.
