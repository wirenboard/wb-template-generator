FROM python:3.12-slim

ARG GIT_SHA=unknown

# curl нужен проверке живости из compose; версии apt не пиним — управляем базовым образом
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY CHANGELOG.md /app/CHANGELOG.md
COPY backend/ .

ENV APP_PORT=9000

LABEL org.opencontainers.image.title="wb-template-generator-backend" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/wirenboard/wb-template-generator"

# Файлы остаются за root, поэтому процесс не перезапишет собственный код
RUN adduser --system --no-create-home --group app
USER app

# exec — чтобы uvicorn получил SIGTERM напрямую и завершился штатно
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${APP_PORT} --no-access-log"]
