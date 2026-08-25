# R0-02 — 비민감 테스트 fixture

- 기록 번호: 002
- 상태: 완료
- 관련 로드맵: R0-02
- 완료 시각: 2026-08-25T05:09:40Z

## 작업한 내용

- FFmpeg 합성 소스로 2초 길이의 무음 `complete.m4a`와 440Hz 톤 `speaker-review.m4a`를 생성했다.
- ffprobe 실패를 검증하기 위한 `corrupt.m4a`를 추가했다.
- 완료 흐름과 화자 검토 흐름의 두 임시 화자, transcript, 분류, 요약 기대 JSON을 추가했다.
- 콘텐츠 SHA-256을 fake 어댑터 선택 키로 사용하는 `manifest.json`을 추가했다.
- fixture의 합성 명령, 비민감 출처, 테스트 목적을 README에 기록했다.

## 검증 결과

- 두 정상 fixture는 ffprobe에서 audio stream과 2초 duration을 반환했다.
- 손상 fixture는 ffprobe에서 실패했다.
- manifest의 SHA-256과 실제 파일 해시가 일치했다.
- manifest 및 기대 결과 JSON 세 파일의 구문 검사가 통과했다.

## 남은 문제와 결정

- 합성 오디오는 실제 발화가 아니므로 STT 정확도 평가에는 사용하지 않는다.
- R3 fake 어댑터는 오디오 내용을 분석하지 않고 manifest의 콘텐츠 해시로 결정적 결과를 반환한다.

## 다음 작업

- R0-03에서 로컬 개발 장비, 향후 RTX 3060 모델 평가 장비, HF_TOKEN 관리 상태를 기록한다.
