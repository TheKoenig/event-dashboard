# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12

# ---- Build stage: install the app and its dependencies into /app/.venv with uv ----
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

# Optional extra CA (e.g. a TLS-inspecting company proxy) for downloading packages.
# Pass it with: docker build --secret id=ca,src=/etc/ssl/certs/ca-certificates.crt .
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src

# Dependencies first so they stay cached when only the source changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --frozen --no-dev --no-install-project

COPY README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --frozen --no-dev --no-editable

# ---- Runtime stage: slim image with only the virtual environment ----
FROM python:${PYTHON_VERSION}-slim

ARG UID=1000
ARG GID=1000

LABEL org.opencontainers.image.title="event-dashboard" \
      org.opencontainers.image.description="Upcoming calendar events as progress bars" \
      org.opencontainers.image.authors="Ruben Koenig <koenig_ruben@outlook.de>" \
      org.opencontainers.image.licenses="MIT"

RUN groupadd --gid "${GID}" app \
    && useradd --no-log-init --uid "${UID}" --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data \
    && chown app:app /data

COPY --from=builder /app/.venv /app/.venv
COPY docker/healthcheck.py /app/healthcheck.py

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    EVENT_DASHBOARD_HOST=0.0.0.0 \
    EVENT_DASHBOARD_CONFIG=/data/config.json

USER app
WORKDIR /data
# 443 (HTTPS) and 80 (HTTP redirect) with TLS; 80 only without TLS.
EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

ENTRYPOINT ["event-dashboard"]
CMD ["serve"]
