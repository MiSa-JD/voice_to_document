# 설정 테스트의 로컬 `.env` 격리

- 기록 번호: 035
- 상태: 완료
- 관련 작업: R4-05 착수 전 기준선 복구
- 작업 브랜치: `feature/r4-05-pyannote-diarization`
- 완료 시각: 2026-08-26T06:41:17Z

## 발견한 문제

저장소 루트에 정상적인 로컬 `.env`가 있고 `SPEECH_MODE`와 `DOCUMENT_MODE`가 설정되어 있으면,
legacy `AI_MODE` 호환성 테스트에서 의도적으로 제거한 두 값이 `.env`에서 다시 주입되었다. 그
결과 애플리케이션 동작과 무관하게 개발자의 로컬 설정에 따라 테스트 결과가 달라졌다.

## 작업한 내용

- legacy 설정 호환성 테스트가 `_env_file=None`으로 실행되게 해 테스트 입력만을 검증하도록 했다.
- 운영 `Settings`의 `.env` 로딩 동작과 다른 설정 테스트의 계약은 변경하지 않았다.

## 검증 결과

- `backend/tests/unit/test_config.py`: 15개 통과
- Ruff format/lint: 변경 파일 통과
- mypy strict: 변경 파일 포함 전체 대상 통과
- `git diff --check`: 통과

## 다음 작업

- 같은 브랜치의 다음 독립 커밋에서 R4-05 pyannote diarization을 구현한다.
