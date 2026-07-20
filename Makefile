.PHONY: help install dev up down migrate test lint format worker \
	frontend-install frontend-dev frontend-build frontend-lint frontend-format

help:
	@echo "ApplyFlow — available targets:"
	@echo "  install            Install Python dev dependencies"
	@echo "  up                 Start the full stack via docker-compose"
	@echo "  down               Stop the stack"
	@echo "  dev                Run the API locally with reload"
	@echo "  worker             Run the Celery worker locally"
	@echo "  migrate            Apply database migrations"
	@echo "  test               Run the test suite"
	@echo "  lint               Run ruff + mypy"
	@echo "  format             Auto-format with black + ruff"
	@echo "  frontend-install   Install frontend dependencies"
	@echo "  frontend-dev       Run the frontend dev server"
	@echo "  frontend-build     Type-check and build the frontend"
	@echo "  frontend-lint      Run eslint on the frontend"
	@echo "  frontend-format    Auto-format the frontend with prettier"

install:
	pip install -r requirements-dev.txt

up:
	docker compose up --build

down:
	docker compose down

dev:
	uvicorn src.interfaces.http.app:app --reload

worker:
	celery -A src.infrastructure.tasks.celery_app.celery_app worker --loglevel=info

migrate:
	alembic upgrade head

test:
	pytest

lint:
	ruff check src tests
	mypy src

format:
	black src tests
	ruff check --fix src tests

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

frontend-lint:
	cd frontend && npm run lint

frontend-format:
	cd frontend && npm run format
