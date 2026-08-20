.PHONY: install run test eval eval-compare lint format typecheck check docker-build docker-up docker-down

install:
	uv sync

run:
	uv run python -m agentic_learning_platform.main

test:
	uv run pytest

eval:
	uv run python -m agentic_learning_platform.evals.run_eval

eval-compare:
	uv run python -m agentic_learning_platform.evals.compare_reports

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run pyright

check: lint typecheck test

docker-build:
	docker build -t agentic-learning-platform:local .

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
