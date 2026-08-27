FROM ghcr.io/astral-sh/uv:0.12.5 AS uv

FROM python:3.11-slim AS backend-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app/backend

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

FROM backend-base AS model-runtime

ENV MODEL_CACHE_ROOT=/models \
    XDG_CACHE_HOME=/models/xdg \
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra speech --no-install-project

COPY --chown=app:app backend ./backend
RUN uv sync --frozen --no-dev --extra speech \
    && mkdir -p /models \
    && chown app:app /models

ENV NLTK_DATA=/nltk

USER app
CMD ["uvicorn", "app.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM backend-base AS runtime

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=app:app backend ./backend
RUN uv sync --frozen --no-dev

USER app
CMD ["uvicorn", "app.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
