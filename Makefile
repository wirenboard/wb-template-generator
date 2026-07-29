# Единый запускатор: одни и те же цели локально и в CI.
# Выкат/откат живут в GitHub Actions (.github/workflows + .github/actions/deploy).

REGISTRY       ?= ghcr.io/wirenboard
IMAGE_BACKEND  := $(REGISTRY)/wb-template-generator-backend
IMAGE_FRONTEND := $(REGISTRY)/wb-template-generator-frontend
TAG            ?= $(shell git rev-parse HEAD)
SHELL_SCRIPTS  := $(wildcard ci/shell/*.sh)

.DEFAULT_GOAL := help
.PHONY: help lint lint-backend lint-frontend lint-shell test test-backend test-frontend \
        build push smoke guard-staleness up down

help: ## показать цели
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

lint: lint-backend lint-frontend lint-shell ## линт+типы обоих подпроектов и скриптов

lint-backend: ## ruff + mypy
	cd backend && ruff check . --config pyproject.toml \
		&& mypy --config-file pyproject.toml models.py template_builder.py jinja_exporter.py

lint-frontend: ## eslint + tsc
	cd frontend && npx eslint . && npx tsc -b

lint-shell: ## shellcheck + bash -n
	@bash -n $(SHELL_SCRIPTS)
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck --severity=warning $(SHELL_SCRIPTS); \
	else echo "⚠️  shellcheck не установлен — проверен только синтаксис"; fi

test: test-backend test-frontend ## тесты обоих подпроектов

test-backend: ## pytest + покрытие
	cd backend && pytest tests/ -v --cov=. --cov-report=term --cov-fail-under=70

test-frontend: ## vitest
	cd frontend && npm test

build: ## собрать образы локально (в CI это делает docker/build-push-action)
	docker build -f backend/Dockerfile  --build-arg GIT_SHA=$(TAG) -t $(IMAGE_BACKEND):$(TAG)  .
	docker build -f frontend/Dockerfile --build-arg GIT_SHA=$(TAG) -t $(IMAGE_FRONTEND):$(TAG) ./frontend

push: ## запушить локально собранные образы
	docker push $(IMAGE_BACKEND):$(TAG)
	docker push $(IMAGE_FRONTEND):$(TAG)

guard-staleness: ## стоп, если ветка отстала от main
	@ci/shell/guard_staleness.sh

smoke: ## проверка живости после выката (URL=https://...)
	@ci/shell/smoke.sh "$(URL)"

up: ## поднять локально (сборка на месте — только dev!)
	docker compose up -d --build

down: ## остановить локально
	docker compose down
