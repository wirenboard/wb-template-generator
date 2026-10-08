.PHONY: lint lint-backend lint-frontend test test-backend test-frontend ci-lint ci-test

lint: lint-backend lint-frontend

lint-backend:
	cd backend && ruff check . --config pyproject.toml \
		&& mypy --config-file pyproject.toml models.py template_builder.py jinja_exporter.py

lint-frontend:
	cd frontend && npx eslint . && npx tsc -b

test: test-backend test-frontend

test-backend:
	cd backend && pytest tests/ -v --cov=. --cov-report=term --cov-fail-under=70

test-frontend:
	cd frontend && npm test

# Образ по ID, а не по тегу: параллельные сборки на общем docker не подменят его друг другу.
ci-lint:
	id=$$(docker build -q -f backend/Dockerfile.ci .) && docker run --rm "$$id" make lint-backend
	id=$$(docker build -q -f frontend/Dockerfile.ci .) && docker run --rm "$$id" make lint-frontend

ci-test:
	id=$$(docker build -q -f backend/Dockerfile.ci .) && docker run --rm "$$id" make test-backend
	id=$$(docker build -q -f frontend/Dockerfile.ci .) && docker run --rm "$$id" make test-frontend
