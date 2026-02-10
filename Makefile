.DEFAULT_GOAL := help

.PHONY: help install lint format typecheck test test-cov docs docs-serve build clean web web-serve

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

web: ## Build the web UI (copy Python sources for Pyodide)
	mkdir -p web/py
	cp src/pto/__init__.py src/pto/holidays.py src/pto/optimizer.py web/py/

web-serve: web ## Serve the web UI locally
	cd web && python3 -m http.server 8080

clean: ## Remove build artifacts
	rm -rf dist/ build/ site/ web/py/ .pytest_cache/ .ruff_cache/ .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
