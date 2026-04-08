.PHONY: test lint typecheck all clean help

help:
	@echo "Available targets:"
	@echo "  all        Run lint + typecheck + tests (default)"
	@echo "  test       Run tests with coverage"
	@echo "  lint       Run ruff linter"
	@echo "  typecheck  Run mypy type checker"
	@echo "  clean      Remove build artifacts"

all: lint typecheck test

test:
	./scripts/run_tests.sh test

lint:
	./scripts/run_tests.sh lint

typecheck:
	./scripts/run_tests.sh typecheck

clean:
	rm -rf htmlcov/ coverage.xml .coverage __pycache__/
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} +
