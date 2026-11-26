FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RTL_SDR__WEB__HOST=0.0.0.0 \
    RTL_SDR__WEB__PORT=8080 \
    RTL_SDR__STORAGE__DB_PATH=/data/events.db \
    RTL_SDR__STORAGE__RECORDINGS_DIR=/recordings

RUN apt-get update && apt-get install -y --no-install-recommends \
        librtlsdr0 \
        rtl-sdr \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir . \
    && mkdir -p /data /recordings

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

CMD ["rtl-sdr-analyzer", "serve", "--host", "0.0.0.0", "--port", "8080"]
