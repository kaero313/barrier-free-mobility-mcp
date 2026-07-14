FROM python:3.12-slim

ARG UV_VERSION=0.10.9

ENV APP_MODE=mock \
    HOME="/home/app" \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR="/home/app/.cache/uv"

WORKDIR /app

RUN pip install --no-cache-dir "uv==${UV_VERSION}"
RUN addgroup --system app \
    && adduser --system --ingroup app --home /home/app app \
    && mkdir -p /home/app/.cache/uv \
    && chown -R app:app /app /home/app

COPY --chown=app:app pyproject.toml uv.lock README.md ./

USER app

RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=app:app app ./app
COPY --chown=app:app .env.example ./.env.example

EXPOSE 8000

CMD ["python", "-m", "app.main"]
