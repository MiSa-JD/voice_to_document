# R3-02 — 가짜 speech/document 어댑터

- 기록 번호: 020
- 상태: 완료
- 관련 로드맵: R3-02
- 완료 시각: 2026-08-25T06:02:52Z

## 작업한 내용

- R0 fixture manifest의 콘텐츠 SHA-256을 기준으로 결과를 선택하는 단일 fake 어댑터를 구현했다.
- 완료 fixture에서 고정 transcript, 두 임시 화자, 회의 classification, 회의 summary를 정규화 schema로 반환하도록 했다.
- speaker-review fixture는 transcript와 두 임시 화자만 반환하고 classification과 summary 요청을 거부하도록 했다.
- segment ID를 recording ID와 순번으로부터 UUID5로 생성해 같은 입력의 결과가 결정적이도록 했다.
- manifest의 expected 경로가 fixture root 밖으로 나가지 못하게 검증했다.

## 검증 결과

- Ruff: 통과
- mypy strict: 통과
- fake adapter 단위 테스트: 4개 통과
- 같은 입력의 transcript 완전 일치: 통과
- 네트워크 socket 사용 금지 상태에서 speech/classification/summary 생성: 통과
- review fixture의 문서 단계 중단과 알 수 없는 콘텐츠 해시 거부: 통과
- fixture 경로 이탈 거부: 통과

## 남은 문제와 결정

- fake 어댑터는 오디오 내용을 분석하지 않고 manifest의 SHA-256만 사용한다.
- 실제 speech/document 공급자 구현과 real 모드 연결은 R4 이후 작업으로 남긴다.

## 다음 작업

- R3-03에서 transcribe, classify, summarize job과 recording 상태 전이를 연결한다.
