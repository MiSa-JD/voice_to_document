# R7-02 구조화 분류 adapter

## 상태

- backend-only 선행 트랙의 P2 완료
- 외부 LLM 호출은 구현하거나 활성화하지 않음

## 변경

- 정규화된 schema v2 transcript와 허용 범주 tuple을 입력으로 받는 분류 인터페이스를 정의했다.
- 출력은 `category`, `confidence`, `reason`, `schema_version=1`을 필수로 검증한다.
- 미허용 범주, 필드 누락, JSON/schema 파손, timeout을 별도 오류 코드로 구분한다.
- committed fixture 응답만 읽는 결정적 fake adapter를 사용한다.
- fake model 이름 및 prompt/schema SHA-256 fingerprint를 adapter 메타데이터로 제공한다.

## 개인정보

- 네트워크를 사용하지 않는 unit test를 포함했다.
- transcript 본문, token, 입력 절대 경로를 로그와 이 문서에 남기지 않았다.
