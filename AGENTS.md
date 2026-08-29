# Repository agent instructions

## GPU verification

- Do not use a sandboxed `nvidia-smi` result to determine whether NVIDIA GPU access works.
  The Codex filesystem/process sandbox can deny NVIDIA device access even when the host and Docker
  GPU runtime are healthy.
- Run GPU availability checks outside the sandbox with explicit escalation. Verify both the host
  (`nvidia-smi`) and Docker (`docker run --gpus all ... nvidia-smi`) before reporting a GPU problem.
- For application-level verification, use `compose.yaml` with `compose.gpu.yaml` and confirm the
  real worker pipeline. Never report “NVIDIA driver unavailable” solely from a sandbox failure.
- Keep private transcript text, private source paths, and credentials out of logs and progress docs.
