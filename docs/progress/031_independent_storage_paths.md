# 독립 호스트 저장 경로 설정

- 기록 번호: 031
- 상태: 완료
- 관련 작업: Compose 저장 경로 설정 보강
- 작업 브랜치: `config/independent-storage-paths`
- 병합 대상: `feature/r4-01-gpu-runtime`
- 완료 시각: 2026-08-26T02:57:46Z

## 작업한 내용

- `RECORDING_INPUT_HOST_DIR`로 Syncthing 입력 폴더의 호스트 경로를 독립 지정하게 했다.
- `TRANSCRIPT_HOST_DIR`로 transcript 결과의 호스트 경로를 독립 지정하게 했다.
- 두 변수가 비어 있으면 기존처럼 `${DATA_ROOT}/inbox`와 `${DATA_ROOT}/transcripts`를 사용한다.
- 컨테이너 내부의 `RECORDING_INPUT_DIR=/data/inbox`와
  `TRANSCRIPT_ROOT=/data/transcripts` 계약은 변경하지 않았다.
- `.env.example`, README, 구현 설계도에 호스트 경로와 컨테이너 경로의 차이, 권한 조건과
  설정 예시를 추가했다.
- Compose smoke가 사용자의 실제 경로 override나 컨테이너 경로 설정을 상속하지 않도록 모든
  테스트 경로를 전용 임시 디렉터리와 절대 컨테이너 경로로 고정했다.

## 설정 예시

```dotenv
RECORDING_INPUT_HOST_DIR=/mnt/syncthing/recordings
TRANSCRIPT_HOST_DIR=/mnt/storage/transcripts
```

입력 경로는 컨테이너에서 읽기 전용으로 연결되고, transcript 경로는 worker가 쓸 수 있어야 한다.

## 검증 결과

- 기본 `docker compose config --quiet`: 통과
- 사용자 지정 호스트 경로의 API mount source/target/read-only 확인: 통과
- fake Compose api/worker/web health: 통과
- Playwright headless Chromium readiness/pipeline: 2개 통과
- worker 재시작 보존 E2E: 1개 통과
- smoke 종료 후 전용 Compose project와 임시 데이터 정리: 통과
- `git diff --check`: 통과

## 비범위

- speaker, summary, app DB의 호스트 경로는 기존 `${DATA_ROOT}` 하위 경로를 유지한다.
- 기존 실제 데이터의 이동이나 복사는 자동으로 수행하지 않는다.
