# syntax=docker/dockerfile:1
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken \
    RAGCOMPASS_WEB_DIST=/app/web/dist \
    RAGCOMPASS_SAMPLE_DIR=/app/examples/corpus
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
RUN uv sync --frozen --no-dev \
    && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
COPY examples/corpus/ examples/corpus/
COPY --from=web /web/dist web/dist
RUN useradd --create-home --uid 10001 ragcompass
USER ragcompass
EXPOSE 8460
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8460/api/health')"
CMD ["uvicorn", "ragcompass.api:app", "--host", "0.0.0.0", "--port", "8460"]
