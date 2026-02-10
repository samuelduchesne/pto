.DEFAULT_GOAL := help

.PHONY: help install lint format typecheck test test-cov docs docs-serve build clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install the package and dev dependencies
	uv sync

lint: ## Run linter and formatter checks
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

format: ## Auto-fix lint issues and format code
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

typecheck: ## Run pyright type checker
	uv run pyright

test: ## Run tests
	uv run pytest

test-cov: ## Run tests with coverage report
	uv run pytest --cov --cov-report=term-missing

docs: ## Build documentation
	uv run mkdocs build

docs-serve: ## Serve documentation locally
	uv run mkdocs serve

build: ## Build the package
	uv build

clean: ## Remove build artifacts
	rm -rf dist/ build/ site/ .pytest_cache/ .ruff_cache/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
