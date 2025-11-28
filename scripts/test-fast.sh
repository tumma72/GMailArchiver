#!/bin/bash
# Run unit and integration tests (no e2e)
uv run pytest tests/unit tests/integration -v -m "unit or integration" --no-cov
