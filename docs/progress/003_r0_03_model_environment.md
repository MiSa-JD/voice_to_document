# R0-03 — 실제 모델 검증 환경

- 기록 번호: 003
- 상태: 완료
- 관련 로드맵: R0-03
- 완료 시각: 2026-08-25T05:10:09Z

## 작업한 내용

- M3 MacBook Air 16GB를 R1~R3 fake 개발 장비로 기록했다.
- Linux RTX 3060 12GB를 향후 R4 실제 모델 평가 장비로 기록했다.
- 현재는 로컬 노트북만 사용하므로 R4 평가를 진행하지 않는다고 명시했다.
- HF_TOKEN은 사용자가 이미 준비한 비밀값이며 `.env` 또는 프로세스 환경으로만 전달하도록 정했다.
- R4 전에 확인할 NVIDIA Container Toolkit, CUDA, 모델 cache, 호환 버전, VRAM 설정 항목을 기록했다.

## 검증 결과

- 환경 결정 문서에 개발 장비, 평가 장비, 접근 범위, R4 미확정 항목이 모두 존재함을 검색으로 확인했다.
- 문서와 README에서 일반적인 Hugging Face/OpenAI 비밀값 패턴이 검출되지 않았다.
- `.env`가 `.gitignore`에 포함된 것을 확인했다.

## 남은 문제와 결정

- RTX 3060 Linux 장비의 driver, Toolkit, Docker GPU 접근은 R4 진입 시 실제 장비에서 검증해야 한다.
- WhisperX/pyannote 호환 버전과 batch size는 실제 평가 없이 확정하지 않는다.

## 다음 작업

- R0-04에서 외부 LLM 전송 허용 상태와 공급자 결정 기한을 기록한다.
