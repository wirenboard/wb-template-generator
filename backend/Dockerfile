FROM python:3.12-slim

# git-SHA запекается в образ → якорь отката и /api/status.revision
ARG GIT_SHA=unknown

# версии apt не пиним: управляем ими через базовый образ
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY CHANGELOG.md /app/CHANGELOG.md
COPY backend/ .

ENV APP_PORT=9000 \
    GIT_SHA=${GIT_SHA}

LABEL org.opencontainers.image.title="wb-template-generator-backend" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/wirenboard/wb-template-generator"

# Файлы остаются за root, поэтому процесс не перезапишет собственный код
RUN adduser --system --no-create-home --group app
USER app
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
  CMD curl -sf "http://127.0.0.1:${APP_PORT}/api/health" || exit 1

# exec — чтобы uvicorn получил SIGTERM напрямую и завершился штатно
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${APP_PORT}"]
