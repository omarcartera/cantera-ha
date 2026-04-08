#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

cd "$REPO_DIR"

MODE="${1:-all}"

install_deps() {
    echo "=== Installing test dependencies ==="
    pip install -q -r requirements_test.txt
}

run_lint() {
    echo "=== Linting with ruff ==="
    ruff check custom_components/cantera/
}

run_typecheck() {
    echo "=== Type checking with mypy ==="
    mypy custom_components/cantera/ --ignore-missing-imports
}

run_tests() {
    echo "=== Running tests with coverage ==="
    pytest tests/ \
        -v \
        --cov=custom_components/cantera \
        --cov-report=term-missing \
        --cov-report=html:htmlcov \
        --cov-report=xml:coverage.xml \
        --tb=short \
        "${@:2}"
    echo ""
    echo "=== Coverage reports: htmlcov/index.html | coverage.xml ==="
}

case "$MODE" in
    lint)
        install_deps
        run_lint
        ;;
    typecheck)
        install_deps
        run_typecheck
        ;;
    test)
        install_deps
        run_tests "$@"
        ;;
    all|"")
        install_deps
        run_lint
        run_typecheck
        run_tests "$@"
        ;;
    *)
        echo "Usage: $0 [all|lint|typecheck|test] [pytest-args...]"
        exit 1
        ;;
esac
