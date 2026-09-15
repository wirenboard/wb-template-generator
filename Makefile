# Локальные команды разработчика. Их же зовёт джоба проверок.

REGISTRY       ?= ghcr.io/wirenboard
IMAGE_BACKEND  := $(REGISTRY)/wb-template-generator-backend
IMAGE_FRONTEND := $(REGISTRY)/wb-template-generator-frontend
TAG            ?= $(shell git rev-parse HEAD)
SMOKE_URL      ?= http://127.0.0.1:8080

.DEFAULT_GOAL := help
.PHONY: help lint lint-backend lint-frontend test test-backend test-frontend \
	ci-lint ci-test build smoke up down

help: ## показать цели
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

lint: lint-backend lint-frontend ## линт и типы обоих подпроектов

lint-backend: ## ruff + mypy
	cd backend && ruff check . --config pyproject.toml \
		&& mypy --config-file pyproject.toml models.py template_builder.py jinja_exporter.py

lint-frontend: ## eslint + tsc
	cd frontend && npx eslint . && npx tsc -b


test: test-backend test-frontend ## тесты обоих подпроектов

test-backend: ## pytest + покрытие
	cd backend && pytest tests/ -v --cov=. --cov-report=term --cov-fail-under=70

test-frontend: ## vitest
	cd frontend && npm test

build: ## собрать образы локально (в CI это делает шаг библиотеки)
	docker build -f backend/Dockerfile  --build-arg GIT_SHA=$(TAG) -t $(IMAGE_BACKEND):$(TAG)  .
	docker build -f frontend/Dockerfile --build-arg GIT_SHA=$(TAG) -t $(IMAGE_FRONTEND):$(TAG) ./frontend



smoke: ## проверка живости (SMOKE_URL=https://...); её же зовёт конвейер после выката
	curl -fsS --retry 3 --max-time 10 -o /dev/null "$(SMOKE_URL)"
	curl -fsS --max-time 10 "$(SMOKE_URL)/api/status" | grep -q revision

up: ## поднять локально (сборка на месте — только dev!)
	docker compose up -d --build

down: ## остановить локально
	docker compose down

# Цели для CI: то же самое, но в контейнере, поэтому не требуют установленных
# локально ruff, mypy и node. Локально удобнее звать lint и test напрямую.
CI_PYTHON ?= python:3.12-slim
CI_NODE ?= node:20-alpine
CI_RUN = docker run --rm -v $(PWD):/src -w /src

ci-lint: ## линт обоих подпроектов в контейнерах
	$(CI_RUN) $(CI_PYTHON) sh -c "pip install --no-cache-dir -q -r backend/requirements.txt && make lint-backend"
	$(CI_RUN) $(CI_NODE) sh -c "apk add --no-cache make >/dev/null && cd frontend && npm ci --silent && cd .. && make lint-frontend"

ci-test: ## тесты обоих подпроектов в контейнерах
	$(CI_RUN) $(CI_PYTHON) sh -c "apt-get update >/dev/null && apt-get install -y --no-install-recommends make poppler-utils >/dev/null && pip install --no-cache-dir -q -r backend/requirements.txt && make test-backend"
	$(CI_RUN) $(CI_NODE) sh -c "apk add --no-cache make >/dev/null && cd frontend && npm ci --silent && cd .. && make test-frontend"
