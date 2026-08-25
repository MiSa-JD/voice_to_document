# 개발 환경과 외부 접근 결정

> 상태: R0 기준 결정 기록
> 비밀값 자체는 이 문서나 Git 저장소에 기록하지 않는다.

## 실제 모델 검증 환경

- 일상 개발 장비: Apple Silicon M3 MacBook Air, 메모리 16GB, macOS
- 개발 원칙: R1~R3는 GPU와 외부 모델 없이 fake 어댑터로 개발하고 검증한다.
- 실제 모델 평가 예정 장비: Linux, NVIDIA RTX 3060 12GB
- 현재 작업 범위: 로컬 노트북에서만 개발하므로 R4 실제 모델 평가는 진행하지 않는다.
- R4 진입 전에 Linux 장비에서 NVIDIA Container Toolkit, 컨테이너 CUDA 접근, 모델 저장 공간, VRAM에 맞는 batch size와 compute type을 확인한다.

## pyannote 접근

- `HF_TOKEN`은 사용자가 이미 준비했으며 사용자가 관리한다.
- 실제 값은 `.env` 또는 배포 환경의 프로세스 환경 변수로만 전달한다.
- `.env`는 Git 추적에서 제외한다.
- 애플리케이션 설정과 로그는 토큰 값을 출력하지 않는다.
- R1~R3의 fake 모드는 `HF_TOKEN` 없이 실행할 수 있어야 한다.
- R4 real 모드에서는 `HF_TOKEN`이 없을 때 변수명을 포함한 설정 오류로 시작을 중단한다.

## LLM 개인정보 경로

- 현재 상태: 외부 LLM API로 transcript를 전송하는 방식을 허용한다.
- 결정 소유자: 사용자
- 실제 공급자, 모델, base URL, API 키는 R7 진입 전에 확정한다.
- R1~R3에서는 fake document 어댑터만 사용하며 실제 transcript를 외부로 전송하지 않는다.
- 외부 전송을 시작하기 전 README와 사용자 화면에 transcript가 외부 서비스로 전송될 수 있음을 표시한다.
- `LLM_API_KEY`는 `.env` 또는 배포 환경의 프로세스 환경 변수로만 전달하고 로그와 artifact에 기록하지 않는다.
- 공급자 선택이 늦어지면 R7/R8의 schema, renderer, UI는 fake 어댑터로 계속 개발하되 실제 transcript 전송은 시작하지 않는다.

## R4 진입 전 미확정 항목

- RTX 3060 장비의 배포 Linux 배포판과 NVIDIA driver 버전
- NVIDIA Container Toolkit 설치 및 Docker GPU smoke 결과
- WhisperX, PyTorch, CUDA, pyannote 호환 버전 조합
- `large-v3` 모델 cache 저장 위치와 사용 가능 디스크
- RTX 3060 12GB에서 재현 가능한 batch size와 compute type
