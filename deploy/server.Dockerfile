# Server image: FastAPI + SQLite. Build context is the repository root:
#   docker build -f deploy/server.Dockerfile -t neurotlon-server:local .
ARG UV_VERSION=0.13.5

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:3.12-slim AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# The lockfile covers the whole workspace, so every member's pyproject must be present.
COPY pyproject.toml uv.lock ./
COPY server/pyproject.toml server/pyproject.toml
COPY launcher/pyproject.toml launcher/pyproject.toml
COPY bci-bridge/pyproject.toml bci-bridge/pyproject.toml
COPY games/pyproject.toml games/pyproject.toml

# Dependencies first: this layer is reused while only the source changes.
RUN uv sync --locked --package neurotlon_server --no-dev --no-install-project

COPY server/ server/
RUN uv sync --locked --package neurotlon_server --no-dev

FROM python:3.12-slim AS runtime
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin neurotlon \
    && mkdir /data \
    && chown neurotlon:neurotlon /data
COPY --from=builder --chown=neurotlon:neurotlon /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    NEUROTLON_DATABASE_URL=sqlite:////data/neurotlon.db \
    NEUROTLON_ALEMBIC_INI=/app/server/alembic.ini
WORKDIR /app
USER neurotlon
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# One worker: SQLite has a single writer. Migrations run before the server starts.
CMD ["sh", "-c", "alembic -c /app/server/alembic.ini upgrade head && exec uvicorn neurotlon_server.app:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
