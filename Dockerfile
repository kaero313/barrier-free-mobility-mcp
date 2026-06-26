FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir uv && uv sync --no-dev

COPY app ./app
COPY .env.example ./.env.example

ENV APP_MODE=mock
EXPOSE 8000

CMD ["uv", "run", "python", "-m", "app.main"]

