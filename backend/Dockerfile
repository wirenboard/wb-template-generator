FROM python:3.12-slim
# curl нужен проверке здоровья в файле выката (роль wb_template_generator в wirenboard/infra)
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY CHANGELOG.md /app/CHANGELOG.md
COPY backend/ .
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision="${GIT_SHA}"
# Файлы остаются за root, поэтому процесс не перезапишет собственный код
RUN adduser --system --no-create-home --group app
USER app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000", "--no-access-log"]
