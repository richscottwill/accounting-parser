# accounting-parser backend image (P1.6)
#
# Two-stage build:
#   1. builder — install poetry + resolve deps into a wheel-house.
#   2. runtime — slim python image with deps + source, no build tools.
#
# Single-arch (linux/amd64) at P1.6. Multi-arch builds (amd64 + arm64)
# land in P3.1 alongside the installer's image-bundling step.

FROM python:3.12-slim AS builder

ENV POETRY_VERSION=2.4.0 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# argon2-cffi needs libffi-dev at build time; psycopg ships wheels so
# no libpq-dev needed. Clean apt lists after install for smaller layer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /app
COPY pyproject.toml poetry.lock* ./
# Resolve deps only first; source copied later so edits don't bust this
# layer. --without dev keeps the image lean (no pytest/ruff/etc.).
RUN poetry install --no-root --without dev

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini* ./
RUN poetry install --only-root


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Runtime deps: curl for the healthcheck; libpq not needed (psycopg
# wheel is self-contained).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. UID 1000 matches the typical host user so bind-mounted
# volumes in dev don't create root-owned files.
RUN useradd --uid 1000 --create-home --shell /bin/bash app
WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src
COPY --from=builder --chown=app:app /app/migrations /app/migrations
COPY --from=builder --chown=app:app /app/alembic.ini* /app/

USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# Uvicorn reload disabled in production. For dev the compose file
# can override CMD to enable --reload with a bind-mount of ./src.
CMD ["uvicorn", "accounting_parser.main:app", "--host", "0.0.0.0", "--port", "8000"]
