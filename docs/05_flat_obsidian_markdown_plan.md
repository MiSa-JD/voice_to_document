# Obsidian 단일 Markdown 출력 기획

> 상태: 구현 전 기획 확정
> 목적: transcript JSON은 내부 저장소에 유지하고, 사람이 읽는 Markdown만 Obsidian root에
> `0001_<첫 발화 20자>.md` 형식으로 저장한다.

## 1. 목표 결과

```text
내부 transcript root/
└── <recording-id>/transcript.json

Obsidian document root/
├── 0001_오늘 회의 목표를 확인하겠습니다.md
├── 0002_다음 작업 일정을 정리합니다.md
└── 0003_일상 대화를 기록합니다.md
```

- JSON은 기존 schema v2, recording ID 디렉터리, revision 계약을 유지한다.
- Markdown만 category/UUID 하위 디렉터리 없이 Obsidian document root에 바로 저장한다.
- Markdown 본문에는 기존 recording ID, revision, 분류, timestamp, `SPEAKER_XX`를 유지한다.

## 2. 파일명 계약

### 문서 번호

- 모든 recording에 전역 단조 증가 `document_sequence`를 한 번만 할당한다.
- 파일명에서는 최소 네 자리로 0-padding한다: `1 → 0001`, `42 → 0042`, `10000 → 10000`.
- 번호는 SQLite transaction 안에서 할당하고 `UNIQUE` 제약으로 동시 worker 충돌을 막는다.
- 재처리, worker 재시작, transcript revision 변경에도 기존 번호를 유지하며 번호를 재사용하지 않는다.

### 짧은 제목

- 시간순 첫 번째 유효 segment의 `text`를 기준으로 최초 `document_title`을 생성한다.
- 연속 공백과 줄바꿈을 단일 공백으로 정규화한 뒤 앞에서 최대 20 Unicode code point를
  사용한다. 20자보다 짧은 발화는 전체를 사용하며, 단어 경계를 맞추기 위한 추가 확장은 하지 않는다.
- `/`, `\\`, NUL, 제어 문자와 파일시스템 예약 문자를 제거하고 앞뒤 공백·마침표를 제거한다.
- 결과가 비면 category slug, category도 없으면 `recording`을 fallback으로 사용한다.
- 제목은 최초 생성 후 DB에 저장하고, 화자 수정이나 재렌더 시 자동으로 바꾸지 않는다.
- 사용자가 나중에 제목 편집 기능을 요청하면 별도 revision 작업으로 다룬다.

### 최종 상대 경로

```text
{document_sequence:04d}_{document_title}.md
```

- DB artifact에는 document root 기준 파일명만 상대 경로로 저장한다.
- sequence가 고유하므로 같은 첫 발화에서 나온 제목끼리도 충돌하지 않는다.
- path traversal과 document root 탈출은 기존 atomic artifact 경로 검증으로 거부한다.

## 3. 설정과 저장 흐름

- host bind mount 전용 `DOCUMENT_HOST_DIR`를 추가한다.
- container 내부 `DOCUMENT_ROOT=/data/documents` 계약은 유지한다.
- 기본 host 경로는 `${DATA_ROOT}/documents`이고, Obsidian을 사용할 때만 다음처럼 지정한다.

```dotenv
TRANSCRIPT_HOST_DIR=
DOCUMENT_HOST_DIR='/home/<user>/hdd/storage/Obsidian/MyVault/3. Resource/vtd'
```

- `.env`의 공백 포함 경로는 backslash escape를 쓰지 않고 전체 값을 작은따옴표로 감싼다.
- worker는 분류된 schema v2 JSON을 transcript root에 먼저 저장한 뒤 Markdown을 document root에
  임시 파일→fsync→`os.replace`로 저장한다.
- Markdown 실패 시 JSON은 보존하고 Markdown artifact는 등록하지 않으며 job을 실패 처리한다.

## 4. DB와 기존 결과 이전

- 새 migration으로 `recordings.document_sequence INTEGER UNIQUE`와
  `recordings.document_title TEXT`를 추가한다.
- 신규 recording은 Markdown 최초 렌더 직전에 sequence/title을 transaction으로 확정한다.
- 기존 recording은 `created_at`, `id` 순서로 빈 sequence를 backfill한다.
- 기존 segment가 있는 recording은 STT를 다시 실행하지 않고 DB segment와 classification으로 새
  Markdown을 렌더한다.
- 새 Markdown 저장과 artifact 상대 경로 갱신이 성공한 뒤에만 기존 UUID 경로 Markdown을 제거한다.
- 이전 중 실패하면 기존 파일·artifact를 유지하고 재실행 가능한 상태로 남긴다.
- transcript JSON은 이동하거나 다시 생성하지 않는다.

## 5. 누락과 재생성 정책

- worker 시작 시 DB에 성공한 `transcript_markdown` artifact가 있지만 실제 파일이 없는 recording을
  검사한다.
- JSON/DB segment/classification과 revision이 일치하면 STT 없이 Markdown만 재렌더한다.
- 필요한 source data 또는 revision이 불일치하면 자동 생성하지 않고 구조화 오류와 audit event를
  남긴다.
- 동일 revision에는 Markdown artifact 하나만 유지한다.

## 6. 테스트와 완료 기준

- Unit: sequence padding·동시 할당, 제목 최대 20자 정규화, 금지 문자·빈 제목 fallback, flat relative path
- Integration: JSON/Markdown root 분리, atomic 실패, 동일 revision, 재시작 멱등성, 누락 Markdown 재생성
- Migration: 기존 recording 순서 backfill, STT 미호출 재렌더, 실패 시 기존 artifact 보존
- Compose: 공백이 있는 `DOCUMENT_HOST_DIR` mount와 worker 쓰기 권한 확인
- 실제 GPU: private 다중 화자 m4a 1개를 처리해 내부 JSON과 Obsidian flat Markdown 생성 확인
- 완료 후 Obsidian root에는 새 Markdown만 존재하고 UUID 디렉터리가 생성되지 않아야 한다.

## 7. 범위 제외

- 실제 LLM 기반 제목·요약 생성
- 사용자가 제목이나 번호를 변경하는 API/GUI
- category별 디렉터리와 날짜별 디렉터리
- transcript JSON의 flat 이동 또는 삭제
- 실제 화자 이름 매핑

첫 발화 일부는 로컬 파일명에 노출되므로 document root의 접근 권한과 동기화 정책은 사용자가
관리한다. transcript 본문이나 token은 로그, progress 문서, audit event에 기록하지 않는다.
