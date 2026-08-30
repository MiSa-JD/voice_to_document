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

- Perform real NVIDIA/GPU verification only when a change affects GPU behavior, including CUDA or
  NVIDIA dependencies, GPU container/runtime configuration, GPU device selection, or a worker path
  that executes on the GPU.
- For changes unrelated to GPU behavior, explicitly state that real NVIDIA/GPU verification is
  unnecessary because the changed path neither uses nor affects the GPU runtime. Run only the
  ordinary checks relevant to the change.
- When real NVIDIA/GPU verification is required, first plan the minimum checks needed for the
  affected behavior, then run only those checks. Do not use a sandboxed `nvidia-smi` result to
  determine whether NVIDIA GPU access works; the Codex filesystem/process sandbox can deny NVIDIA
  device access even when the host and Docker GPU runtime are healthy.
- Run required GPU availability checks outside the sandbox with explicit escalation. Check only the
  layers relevant to the change: use host `nvidia-smi` for host access, Docker
  (`docker run --gpus all ... nvidia-smi`) for container runtime access, and `compose.yaml` with
  `compose.gpu.yaml` plus the real worker pipeline for application-level behavior.
- If the required real NVIDIA/GPU verification cannot be completed in the current development
  environment, move the development environment to the operations server and repeat the required
  checks there before reporting the verification result. Never report “NVIDIA driver unavailable”
  solely from a sandbox failure.
- Keep private transcript text, private source paths, and credentials out of logs and progress docs.
