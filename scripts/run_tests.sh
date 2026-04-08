#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

cd "$REPO_DIR"

echo "=== Installing test dependencies ==="
pip install -q -r requirements_test.txt

echo "=== Running tests with coverage ==="
pytest tests/ \
    -v \
    --cov=custom_components/cantera \
    --cov-report=term-missing \
    --cov-report=html:htmlcov \
    --cov-report=xml:coverage.xml \
    --tb=short \
    "$@"

echo ""
echo "=== Coverage report generated in htmlcov/ ==="
echo "=== XML report: coverage.xml ==="
