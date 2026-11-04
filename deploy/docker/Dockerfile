FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AGW_PROJECT_ROOT=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY migrations ./migrations
COPY src ./src

RUN pip install .

RUN useradd --create-home --uid 10001 agw \
    && mkdir -p /data/ca \
    && chown -R agw:agw /app /data

USER agw

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

CMD ["agw", "serve", "--host", "0.0.0.0", "--port", "8080"]
