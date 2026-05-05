.PHONY: install test run lint docker-up docker-down demo

install:
	uv sync

test:
	uv run pytest tests/ -v

run:
	uv run python -m optirc.api.main

lint:
	uv run black src/ tests/
	uv run isort src/ tests/
	uv run mypy src/

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

demo:
	uv run python demo.py

health:
	curl http://localhost:8000/v1/health
