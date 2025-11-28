#!/bin/bash
# Run unit tests only (fast, no I/O)
uv run pytest tests/unit -v -m "unit" --no-cov
