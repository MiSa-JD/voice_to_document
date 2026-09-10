# R9-01 복구 경계 보강과 스택 재검증

작성일: 2026-09-10. 브랜치: `feature/r9-01-stale-job-recovery → main`.
선행 구현 095·096. 후속 #57/R9-03은 이 수정 뒤 순서대로 rebase한다.

최종 검토에서 이전 revision의 render 입력도 녹음 ID·revision·콘텐츠 해시를 검증하도록 보강했다.
완료된 render의 현재 JSON/Markdown이 검증되면 3회 상한에서도 재실행 없이 성공 복구한다.
요약 template과 category 일치도 검사한다. 완료 결과 재사용과 입력 재개 판단을 공통 함수로 유지한다.

선행 작업의 완료 복구가 이미 failed인 후속 작업을 새로 등록하지 않도록 후속 상태를 먼저 검사한다.
후속 입력 fingerprint가 달라졌으면 안전한 충돌로 남기고, 활성 작업 unique 제약 오류로
worker 전체가 시작 실패하지 않도록 한다. 클립·분류·요약 재개 후 상태 정리도 같은 트랜잭션
경로를 사용한다. SUMMARY_INVALID_OUTPUT의 자동 재시도 범위를 확대하지 않는다.

추가 회귀 6개: 이전 JSON의 ID/revision/content hash 불일치(등록 해시는 재계산한 경우),
실패한 요약 후속 작업 보존, 후속 fingerprint 충돌, 완료 render의 시도 상한 복구.
복구 회귀 총 19개, backend 전체 566개, frontend 33개 통과.
096의 전체 format/lint/typecheck/OpenAPI/생성 타입/diff 검사와 make compose-smoke를 재실행해
모두 통과했다. Compose 기본 브라우저 3개, 재시작 보존 1개, SIGKILL recovery_probe 통과.
실제 GPU는 미완료이며 서버 인계 상태를 유지한다.

## 실제 GPU checkpoint를 정확히 중단하는 서버 보조 명령

아래는 **실행 결과가 아니라 서버 인계 명령**이다. 096의 격리 설정과 구 worker 종료 규칙을 따른다.
각 시나리오는 별도의 빈 project·DB·출력 디렉터리와 사용 허가된 입력 한 건으로 수행한다.
.env.r9-checkpoint에는 이 시나리오 전용 경로, SPEECH_MODE=real, DOCUMENT_MODE=fake를 설정한다.
정상 worker를 먼저 중지하고, 아래 일회성 프로세스에서만 테스트 hook을 적용한다.
실제 모델·전사·정렬·화자 분리·JSON 저장을 수행한 뒤 클립 생성 직전에 SIGKILL한다.

```sh
docker compose --env-file .env.r9-checkpoint -f compose.yaml -f compose.gpu.yaml stop worker
docker compose --env-file .env.r9-checkpoint -f compose.yaml -f compose.gpu.yaml run --rm --no-deps -T worker python - <<'PY'
import logging
import os
import signal
from app.config import Settings
from app.worker import build_handler, run

settings = Settings()
assert settings.effective_speech_mode == "real"
handler = build_handler(settings, logging.getLogger("worker"))
def stop_after_transcript(*args):
    os.kill(os.getpid(), signal.SIGKILL)
handler._generate_speaker_clips = stop_after_transcript
run(settings, handler)
PY
# 137 종료는 이 시나리오의 의도된 SIGKILL이다. 정상 worker로 재개한다.
docker compose --env-file .env.r9-checkpoint -f compose.yaml -f compose.gpu.yaml up -d worker
```

기대: running transcribe를 회수해 같은 ID·증가한 attempts로 재개하고, transcript JSON과
segment ID를 덮어쓰지 않으며 클립·후속 job은 중복되지 않는다. 위 hook은 파일에 저장하지 않아
정상 worker에 남지 않는다. GPU 모델 접근이 먼저 실패했다면 checkpoint에 도달한 것으로 보고하지 않는다.

R9-02 실제 재시도 검증에는 또 다른 빈 .env.r9-retry 환경에서 아래처럼 실제 전사 호출 뒤
의도된 테스트 실패를 주입할 수 있다. 이는 GPU 고장 재현이 아니라 실제 GPU 실행을 거친
작업의 수동 재시도 계약 검증이다. 정상 worker는 중지하고 전용 API/web만 실행한 상태로 진행한다.

```sh
docker compose --env-file .env.r9-retry -f compose.yaml -f compose.gpu.yaml run --rm --no-deps -T worker python - <<'PY'
import logging
from app.config import Settings
from app.runtime import PermanentJobError
from app.worker import build_handler, run

settings = Settings()
assert settings.effective_speech_mode == "real"
handler = build_handler(settings, logging.getLogger("worker"))
transcribe = handler.transcription_adapter.transcribe
def fail_after_gpu(*args, **kwargs):
    transcribe(*args, **kwargs)
    raise PermanentJobError("TRANSCRIPTION_FAILED", "검증용 일회성 실패입니다.")
handler.transcription_adapter.transcribe = fail_after_gpu
run(settings, handler)
PY
```

전용 UI에서 실패 확인 후 위 일회성 프로세스를 Ctrl+C로 종료하고 정상 worker를 시작한다.
처리 이력의 전사 재시도를 눌러 원 failed job 보존, 새 job attempts=1부터 시작,
실제 전사 완료를 확인한다. 자동 화자 embedding 접근이 막히면 그 항목의 미검증 사유만
분리해 기록한다. 모델 접근 승인·평가 표본 R6 blocker는 유지한다.
원문·경로·credential·공급자 응답은 공유하지 않으며 결과에는 ID·상태·횟수·오류 코드만 남긴다.
