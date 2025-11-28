#!/bin/bash
# Run all tests with coverage
uv run pytest tests/ -v --cov=gmailarchiver --cov-report=term-missing
