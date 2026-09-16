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

smoke: ## проверка живости руками (SMOKE_URL=https://...)
	curl -fsS --retry 3 --max-time 10 -o /dev/null "$(SMOKE_URL)"
	curl -fsS --max-time 10 "$(SMOKE_URL)/api/status" | grep -q revision

up: ## поднять локально (сборка на месте — только dev!)
	docker compose up -d --build

down: ## остановить локально
	docker compose down

# Те же проверки внутри образа с инструментами — на агенте нужен только docker.
CI_BACKEND ?= wb-template-generator-ci-backend
CI_FRONTEND ?= wb-template-generator-ci-frontend

ci-lint: ## линт обоих подпроектов в образах с инструментами
	docker build -q -f backend/Dockerfile.ci -t $(CI_BACKEND) .
	docker run --rm $(CI_BACKEND) make lint-backend
	docker build -q -f frontend/Dockerfile.ci -t $(CI_FRONTEND) .
	docker run --rm $(CI_FRONTEND) make lint-frontend

ci-test: ## тесты обоих подпроектов в образах с инструментами
	docker build -q -f backend/Dockerfile.ci -t $(CI_BACKEND) .
	docker run --rm $(CI_BACKEND) make test-backend
	docker build -q -f frontend/Dockerfile.ci -t $(CI_FRONTEND) .
	docker run --rm $(CI_FRONTEND) make test-frontend
