.PHONY: install lint format typecheck test test-live check

# This is a public repo: never resolve against a locally configured private
# index (e.g. the CodeArtifact default set by corporate shell integrations).
unexport UV_DEFAULT_INDEX
unexport UV_INDEX_URL

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest -m "not live"

test-live:
	uv run pytest -m live

check: lint typecheck test
