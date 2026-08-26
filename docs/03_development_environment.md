# 개발 환경과 외부 접근 결정

> 상태: R4-01 진입 조건 갱신
> 비밀값 자체는 이 문서나 Git 저장소에 기록하지 않는다.

## 실제 모델 검증 환경

- 일상 개발 장비: Apple Silicon M3 MacBook Air, 메모리 16GB, macOS
- 개발 원칙: R1~R3는 GPU와 외부 모델 없이 fake 어댑터로 개발하고 검증한다.
- 실제 모델 평가 장비: Linux x86_64, NVIDIA RTX 3060 12GB
- 2026-08-26 사용자 사전 검증: 호스트 `nvidia-smi`와 `docker run --rm --gpus all ubuntu:22.04 nvidia-smi` 통과
- 2026-08-26 `make model-smoke` 통과: RTX 3060, driver 535.309.01, Torch CUDA 12.8,
  Torch 2.8.0+cu128, WhisperX 3.8.6, pyannote.audio 4.0.7
- 일반 개발·CI·기본 Compose는 계속 fake runtime을 사용하며 GPU를 예약하지 않는다.

## pyannote 접근

- `HF_TOKEN`은 사용자가 이미 준비했으며 사용자가 관리한다.
- `pyannote/speaker-diarization-community-1` 사용 조건은 사용자가 승인했다.
- 실제 값은 `.env` 또는 배포 환경의 프로세스 환경 변수로만 전달한다.
- `.env`는 Git 추적에서 제외한다.
- 애플리케이션 설정과 로그는 토큰 값을 출력하지 않는다.
- R1~R3의 fake 모드는 `HF_TOKEN` 없이 실행할 수 있어야 한다.
- `SPEECH_MODE=real`에서는 `HF_TOKEN`이 없을 때 변수명을 포함한 설정 오류로 시작을 중단한다.
- `DOCUMENT_MODE=fake`는 R4 speech 검증 중 LLM 자격증명을 요구하지 않는다.

## LLM 개인정보 경로

- 현재 상태: 외부 LLM API로 transcript를 전송하는 방식을 허용한다.
- 결정 소유자: 사용자
- 실제 공급자, 모델, base URL, API 키는 R7 진입 전에 확정한다.
- R1~R3에서는 fake document 어댑터만 사용하며 실제 transcript를 외부로 전송하지 않는다.
- 외부 전송을 시작하기 전 README와 사용자 화면에 transcript가 외부 서비스로 전송될 수 있음을 표시한다.
- `LLM_API_KEY`는 `.env` 또는 배포 환경의 프로세스 환경 변수로만 전달하고 로그와 artifact에 기록하지 않는다.
- 공급자 선택이 늦어지면 R7/R8의 schema, renderer, UI는 fake 어댑터로 계속 개발하되 실제 transcript 전송은 시작하지 않는다.

## R4 잔여 확인 항목

- 고정 조합: WhisperX 3.8.6, PyTorch/Torchaudio 2.8.0, Torchvision 0.23.0, CUDA 12.8 wheel
- `large-v3`와 pyannote 모델 cache의 실제 사용량 및 사용 가능 디스크
- RTX 3060 12GB에서 재현 가능한 batch size와 compute type
