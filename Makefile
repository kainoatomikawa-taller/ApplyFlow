.PHONY: help install dev up down migrate test lint format worker

help:
	@echo "ApplyFlow — available targets:"
	@echo "  install   Install Python dev dependencies"
	@echo "  up        Start the full stack via docker-compose"
	@echo "  down      Stop the stack"
	@echo "  dev       Run the API locally with reload"
	@echo "  worker    Run the Celery worker locally"
	@echo "  migrate   Apply database migrations"
	@echo "  test      Run the test suite"
	@echo "  lint      Run ruff + mypy"
	@echo "  format    Auto-format with black + ruff"

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
