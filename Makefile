# wb-template-generator — единый запускатор (стандарт деплоя, PRJ-1089).
# Порядок: тонкий workflow → make <цель> → (при необходимости) ci/-скрипт.
# Переносимые цели (lint/test/build) одинаковы локально и в CI; deploy/rollback — env-bound.

REGISTRY       ?= ghcr.io/wirenboard
IMAGE_BACKEND  := $(REGISTRY)/wb-template-generator-backend
IMAGE_FRONTEND := $(REGISTRY)/wb-template-generator-frontend
# TAG по умолчанию = текущий git-SHA (неизменяемый якорь)
TAG            ?= $(shell git rev-parse HEAD)
SHELL_SCRIPTS  := $(wildcard ci/shell/*.sh)

.PHONY: help lint lint-backend lint-frontend lint-shell test test-backend test-frontend \
        build push deploy rollback smoke guard-staleness conformance up down

help: ## показать цели
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

## ── Переносимое: одинаково на ноутбуке и в CI ───────────────────────────────
lint: lint-backend lint-frontend lint-shell ## линт+типы обоих подпроектов и скриптов выката

lint-backend: ## ruff + mypy (backend)
	cd backend && ruff check . --config pyproject.toml \
		&& mypy --config-file pyproject.toml models.py template_builder.py jinja_exporter.py

lint-frontend: ## eslint + tsc (frontend)
	cd frontend && npx eslint . && npx tsc -b

# Скрипты выката — такой же прод-код, как приложение: они ходят на боевой сервер.
# Без линта опечатка в bash вылезает в самый неудобный момент — при аварийном откате.
# Если shellcheck не установлен — гоняем хотя бы синтаксис (bash -n), но не молчим.
lint-shell: ## shellcheck + bash -n на ci/shell/*.sh
	@bash -n $(SHELL_SCRIPTS) && echo "✅ bash -n ok"
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck --severity=warning $(SHELL_SCRIPTS) && echo "✅ shellcheck ok"; \
	else \
		echo "⚠️  shellcheck не установлен — проверен только синтаксис (в CI shellcheck обязателен)"; \
	fi

test: test-backend test-frontend ## тесты обоих подпроектов

test-backend: ## pytest + покрытие (backend)
	cd backend && pytest tests/ -v --cov=. --cov-report=term --cov-fail-under=70

test-frontend: ## vitest (frontend)
	cd frontend && npm test

build: ## собрать оба образа с git-SHA (TAG=<sha>)
	docker build -f backend/Dockerfile  --build-arg GIT_SHA=$(TAG) -t $(IMAGE_BACKEND):$(TAG)  .
	docker build -f frontend/Dockerfile --build-arg GIT_SHA=$(TAG) -t $(IMAGE_FRONTEND):$(TAG) ./frontend

push: ## запушить образы TAG в реестр
	docker push $(IMAGE_BACKEND):$(TAG)
	docker push $(IMAGE_FRONTEND):$(TAG)

## ── Привязано к среде: только через CI/сервер ───────────────────────────────
guard-staleness: ## стоп, если ветка отстала от main
	@ci/shell/guard_staleness.sh

conformance: ## проверка соответствия prod-ready гейту (🔒 hard / 👁 monitor)
	@ci/shell/conformance.sh

deploy: ## выкат TAG на сервер: compose из git @ TAG → pull → rolling → verify (last-good пишет workflow ПОСЛЕ smoke)
	@ci/shell/deploy.sh "$(TAG)"

rollback: ## откат: redeploy прошлого хорошего SHA (или TAG=<sha>)
	@ci/shell/rollback.sh "$(TAG)"

smoke: ## проверка живости после выката (URL=https://...)
	@ci/shell/smoke.sh "$(URL)"

## ── Локальная разработка ────────────────────────────────────────────────────
up: ## поднять локально (сборка на месте — только dev!)
	docker compose up -d --build

down: ## остановить локально
	docker compose down
