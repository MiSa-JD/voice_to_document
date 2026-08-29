# Repository agent instructions

## Pull request workflow

- Publish consecutive, dependent roadmap work as stacked PRs by default. Create the first branch from
  `main`, each following branch from its immediate predecessor, and set each PR base to that
  predecessor branch.
- Before implementation, state the planned stack order and keep each PR independently reviewable,
  tested, documented, and focused on one roadmap item or coherent boundary.
- Write PR titles, bodies, verification results, and predecessor/successor relationships in Korean.
- Merge stacks from oldest to newest. After each merge, rebase the next branch when necessary and
  change its PR base to `main`; then re-run checks before merging it.
- If an earlier branch changes, rebase every affected descendant in order, use
  `git push --force-with-lease` rather than an unconditional force push, and verify all PR base/head
  relationships and checks again.
- Use an independent PR instead when work is unrelated, can be merged in any order, is an urgent
  hotfix, or the user explicitly requests a standalone PR. Do not merge PRs unless the user asks.
- Follow `docs/06_stacked_pull_request_workflow.md` for the full procedure and PR template.

## GPU verification

- Do not use a sandboxed `nvidia-smi` result to determine whether NVIDIA GPU access works.
  The Codex filesystem/process sandbox can deny NVIDIA device access even when the host and Docker
  GPU runtime are healthy.
- Run GPU availability checks outside the sandbox with explicit escalation. Verify both the host
  (`nvidia-smi`) and Docker (`docker run --gpus all ... nvidia-smi`) before reporting a GPU problem.
- For application-level verification, use `compose.yaml` with `compose.gpu.yaml` and confirm the
  real worker pipeline. Never report “NVIDIA driver unavailable” solely from a sandbox failure.
- Keep private transcript text, private source paths, and credentials out of logs and progress docs.
