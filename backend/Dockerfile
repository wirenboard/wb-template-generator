FROM python:3.12-slim

# PRJ-1089 pilot: git-SHA запекается в образ → якорь отката/аудита и /api/status.revision
ARG GIT_SHA=unknown

# версии apt-пакетов не пиним намеренно: базовый образ пиннится сам — управляем версиями
# через базу, а не построчно (DL3015 закрыт через --no-install-recommends)
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY CHANGELOG.md /app/CHANGELOG.md
COPY backend/ .

# Единый порт 9000. Раньше CMD/HEALTHCHECK были на :8000, а сервис реально запускается
# на :9000 (переопределялось в compose) — образ был не запускаем standalone и его
# HEALTHCHECK всегда падал вне compose. PRJ-1089 требует самосогласованный образ.
ENV APP_PORT=9000 \
    GIT_SHA=${GIT_SHA}

LABEL org.opencontainers.image.title="wb-template-generator-backend" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/wirenboard/wb-template-generator"

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
  CMD curl -sf "http://localhost:${APP_PORT}/api/health" || exit 1

# exec: uvicorn становится PID 1 и получает SIGTERM напрямую. Без exec сигнал уходит
# в sh, который его не пересылает — контейнер не завершается по-хорошему, и docker
# добивает его через 10с (обрубленные запросы при каждом rolling-update).
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${APP_PORT}"]
