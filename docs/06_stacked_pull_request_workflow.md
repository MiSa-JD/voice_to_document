# Stacked Pull Request 작업 방식

## 목적

연속된 로드맵 작업을 하나의 큰 PR로 합치지 않고, 검토 가능한 경계별로 나누면서도 다음 작업을
기다리지 않고 진행한다. 이 저장소에서는 서로 의존하는 연속 작업을 기본적으로 stacked PR로
게시한다.

stacked PR은 각 PR이 바로 앞 PR의 브랜치를 base로 사용하는 형태다.

```text
main
└── feature/r6-01-profile-foundation        PR A → main
    └── feature/r6-02-profile-matching      PR B → feature/r6-01-profile-foundation
        └── feature/r6-03-profile-review    PR C → feature/r6-02-profile-matching
```

## 적용 기준

다음 조건이면 stacked PR을 사용한다.

- 같은 마일스톤 또는 하나의 사용자 흐름에 속한 연속 로드맵 항목이다.
- 후속 작업이 선행 작업의 schema, API, component 또는 내부 계약에 의존한다.
- 각 항목을 별도로 검토하고 검증할 수 있지만 순서대로 병합해야 한다.
- 선행 PR 검토를 기다리는 동안 후속 작업을 안전하게 진행할 수 있다.

다음 경우에는 독립 PR을 사용한다.

- 변경끼리 의존성이 없고 어떤 순서로도 병합할 수 있다.
- 운영 장애나 보안 문제를 고치는 긴급 hotfix다.
- 현재 stack과 무관한 문서, 설정 또는 유지보수 변경이다.
- 사용자가 standalone PR을 명시적으로 요청했다.

작업 크기가 크다는 이유만으로 stack을 만들지는 않는다. 먼저 각 PR이 하나의 로드맵 항목 또는
응집된 계약 경계를 갖는지 확인한다.

## 시작 전 계획

구현 전에 다음 내용을 사용자에게 알리고 작업 계획에도 반영한다.

1. PR별 범위와 제외 범위
2. 브랜치 이름과 base 관계
3. 예상 병합 순서
4. 각 PR에서 실행할 검증
5. 공통 계약 변경이 어느 PR에 처음 포함되는지

예시는 다음과 같다.

```text
1. feature/r6-01-profile-foundation → main
2. feature/r6-02-profile-matching → feature/r6-01-profile-foundation
3. feature/r6-03-profile-review → feature/r6-02-profile-matching
```

## 브랜치와 커밋 절차

첫 브랜치는 최신 `main`에서 만든다.

```bash
git switch main
git pull --ff-only
git switch -c feature/r6-01-profile-foundation
```

첫 작업을 구현·검증·커밋한 뒤 다음 브랜치를 현재 브랜치에서 만든다.

```bash
git switch -c feature/r6-02-profile-matching
```

각 PR은 다음 원칙을 지킨다.

- 하나의 로드맵 항목 또는 응집된 변경 경계에 집중한다.
- 선행 PR의 변경을 중복 구현하거나 복사하지 않는다.
- 구현, 해당 테스트, OpenAPI/생성 타입, 진행 문서를 같은 PR에 포함한다.
- 커밋 수보다 review 가능성을 우선하되 불필요한 임시 커밋은 게시 전에 정리한다.
- 비공개 transcript, 원본 절대 경로, credential을 커밋·로그·진행 문서에 넣지 않는다.

## PR 게시

첫 PR은 `main`, 후속 PR은 바로 앞 브랜치를 base로 지정한다.

```bash
gh pr create \
  --base main \
  --head feature/r6-01-profile-foundation

gh pr create \
  --base feature/r6-01-profile-foundation \
  --head feature/r6-02-profile-matching
```

PR 제목과 본문은 한국어로 작성한다. 본문에는 최소한 다음 내용을 포함한다.

```markdown
## 요약

- 이 PR의 독립적인 변경과 사용자 영향을 설명한다.

## 검증

- 실행한 정적 검사, unit/integration/E2E와 결과를 기록한다.
- 생략한 검사가 있으면 이유를 기록한다.

## 스택 관계

- base: `feature/r6-01-profile-foundation` (선행 PR #번호)
- 선행: PR #번호 → 이 PR → 후속 PR #번호
- 선행 PR 병합 후 base를 `main`으로 정리한다.

## 비범위

- 후속 PR 또는 다른 마일스톤에 남긴 작업을 기록한다.
```

PR을 만든 뒤 번호가 확정되면 선행·후속 PR 본문에 서로의 링크를 추가한다. PR을 자동으로
병합하지 않으며 사용자가 병합을 요청하거나 승인할 때까지 open 상태로 둔다.

## 검증 규칙

각 브랜치는 선행 브랜치를 포함한 해당 시점의 전체 tree로 검증한다. 후속 PR이 선행 PR의 검증을
대체하지 않는다.

기본 검증은 다음과 같다.

```bash
make check-format
make lint
make typecheck
make api-schema-check
make test-unit
make test-integration
make test-frontend
```

Compose, 브라우저 E2E, 실제 모델 또는 GPU 검증은 변경 범위와 repository 지침에 따라 추가한다.
GitHub Actions가 실패하면 로컬 통과만으로 완료 처리하지 않고 실패 원인을 고친 뒤 stack 전체에
필요한 변경을 전파한다.

## 선행 PR이 변경됐을 때

검토 중 선행 브랜치가 바뀌면 영향받는 하위 브랜치를 오래된 순서대로 재배치한다.

```text
main
└── A'       선행 수정 완료
    └── B'   A' 위로 rebase
        └── C'   B' 위로 rebase
```

절차는 다음과 같다.

1. 선행 브랜치 수정과 검증을 완료한다.
2. 해당 브랜치를 push한다.
3. 바로 다음 브랜치를 새 선행 tip 위로 rebase한다.
4. 충돌을 해결하고 그 브랜치의 전체 검증을 다시 실행한다.
5. 더 아래 브랜치에도 같은 절차를 반복한다.
6. 재작성된 브랜치는 `git push --force-with-lease`로만 갱신한다.
7. 모든 PR의 base/head와 GitHub 검사를 다시 확인한다.

공유 브랜치에 무조건적인 `git push --force`를 사용하지 않는다. 이미 다른 사람이 추가한 원격
커밋이 있으면 강제 갱신을 중단하고 먼저 변경 소유자와 조정한다.

## 병합과 base 정리

stack은 가장 오래된 PR부터 한 개씩 병합한다.

1. 선행 PR의 필수 검사가 모두 성공했는지 확인한다.
2. 사용자의 병합 요청 또는 승인을 확인한 뒤 선행 PR을 병합한다.
3. 로컬 `main`과 원격 `main`을 갱신한다.
4. 다음 브랜치가 새 `main`의 ancestry를 그대로 포함하는지 확인한다.
5. squash/rebase merge로 commit identity가 바뀌었으면 다음 브랜치를 새 `main` 위로 rebase한다.
6. 다음 PR의 base를 `main`으로 바꾸고 diff가 그 PR 고유 변경만 포함하는지 확인한다.
7. 검사를 다시 실행하고 성공하면 같은 순서로 다음 PR을 병합한다.

예시는 다음과 같다.

```bash
git switch feature/r6-02-profile-matching
git rebase main                    # 필요한 경우에만
git push --force-with-lease        # rebase로 history가 바뀐 경우에만
gh pr edit <PR-number> --base main
gh pr diff <PR-number>
gh pr checks <PR-number>
```

모든 PR이 병합된 뒤에는 최종 `main`에서 전체 검증을 한 번 더 실행하고, 원격에 남은 임시 브랜치는
복구 필요성이 없는지 확인한 후 정리한다.

## 완료 체크리스트

- [ ] 각 PR이 하나의 명확한 변경 경계를 가진다.
- [ ] 첫 PR은 `main`, 후속 PR은 바로 앞 브랜치를 base로 한다.
- [ ] 모든 PR 본문에 검증 결과와 stack 관계가 한국어로 기록됐다.
- [ ] 선행 변경을 하위 브랜치에 순서대로 재배치했다.
- [ ] 각 PR의 로컬 검사와 GitHub 검사가 성공했다.
- [ ] base/head가 계획한 순서와 일치한다.
- [ ] 사용자의 승인 없이 PR을 병합하지 않았다.
- [ ] 병합 후 다음 PR의 base와 diff를 다시 확인했다.
- [ ] 비공개 데이터와 credential이 기록되지 않았다.
