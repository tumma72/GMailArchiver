# Coverage Badge Setup Guide

The coverage badge in README.md is configured to pull from a GitHub Gist. This guide explains how to set it up.

## Option 1: Automated Coverage Badge (Recommended)

### Prerequisites
- GitHub account
- Repository with GitHub Actions enabled

### Step-by-Step Setup

1. **Create a GitHub Gist**
   - Go to https://gist.github.com/
   - Create a new secret or public gist (public recommended for badge visibility)
   - Name it something like `gmailarchiver-coverage-badge`
   - Add a file called `coverage-badge.json` with this initial content:
     ```json
     {
       "schemaVersion": 1,
       "label": "coverage",
       "message": "unknown",
       "color": "lightgrey"
     }
     ```
   - Create the gist and copy the **Gist ID** from the URL (the long alphanumeric string)

2. **Create a GitHub Personal Access Token**
   - Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Click "Generate new token (classic)"
   - Give it a descriptive name like "GMailArchiver Coverage Badge"
   - Select only the `gist` scope
   - Click "Generate token"
   - **Copy the token immediately** (you won't be able to see it again)

3. **Add Configuration to Your Repository**
   - Go to your repository Settings → Secrets and variables → Actions

   - **Add Secret** (click "New repository secret"):
     - Name: `GIST_TOKEN`
     - Value: (paste the personal access token from step 2)

   - **Add Variable** (click "Variables" tab, then "New repository variable"):
     - Name: `GIST_ID`
     - Value: (paste the Gist ID from step 1)

   > **Why Variable instead of Secret?** The Gist ID is already public (visible in the README badge URL), so there's no security benefit to hiding it. Using a variable means you only define it once and it's used in both the workflow and README.

4. **Update README.md**
   - Replace the static coverage badge on line 7 with a dynamic one using your Gist ID
   - Change this:
     ```markdown
     [![Coverage](https://img.shields.io/badge/coverage-30%25-orange)](https://github.com/tumma72/GMailArchiver/actions)
     ```
   - To this (replace `YOUR_USERNAME` and `YOUR_GIST_ID`):
     ```markdown
     [![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/YOUR_USERNAME/YOUR_GIST_ID/raw/coverage-badge.json)](https://github.com/tumma72/GMailArchiver/actions)
     ```
   - Example:
     ```markdown
     [![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/tumma72/a1b2c3d4e5f6/raw/coverage-badge.json)](https://github.com/tumma72/GMailArchiver/actions)
     ```

5. **Trigger the Workflow**
   - Push a commit to the main branch
   - The coverage workflow will run automatically
   - After completion, check your Gist - it should be updated with actual coverage data
   - The badge in your README will now show the real coverage percentage

## Option 2: Simple Static Badge

If you prefer not to set up automation, you can use a simple static badge:

1. Run tests locally to get coverage:
   ```bash
   uv run pytest --cov=src/gmailarchiver --cov-report=term
   ```

2. Note the coverage percentage from the output

3. Update README.md line 7 to use a static badge:
   ```markdown
   [![Coverage](https://img.shields.io/badge/coverage-30%25-orange)](https://github.com/tumma72/GMailArchiver)
   ```

4. Update the percentage and color manually after each release:
   - Red: `red` (< 40%)
   - Orange: `orange` (40-59%)
   - Yellow: `yellow` (60-79%)
   - Green: `brightgreen` (≥ 80%)

## Option 3: Use Codecov or Coveralls

For more advanced coverage reporting with history and PR comments:

### Codecov
1. Sign up at https://codecov.io/ with your GitHub account
2. Enable your repository
3. Add this to your workflow (already included in `.github/workflows/coverage.yml`):
   ```yaml
   - uses: codecov/codecov-action@v3
     with:
       files: ./coverage.xml
   ```
4. Update README.md badge:
   ```markdown
   [![Coverage](https://codecov.io/gh/tumma72/GMailArchiver/branch/main/graph/badge.svg)](https://codecov.io/gh/tumma72/GMailArchiver)
   ```

### Coveralls
1. Sign up at https://coveralls.io/ with your GitHub account
2. Enable your repository
3. Add coveralls to your dependencies and update workflow
4. Update README.md badge:
   ```markdown
   [![Coverage](https://coveralls.io/repos/github/tumma72/GMailArchiver/badge.svg?branch=main)](https://coveralls.io/github/tumma72/GMailArchiver?branch=main)
   ```

## Current Coverage

As of v1.0.1, the actual coverage is **30%** (focused on core modules with comprehensive test coverage for auth, state, path validation, and utilities).

To improve coverage, add tests for:
- `archiver.py` (0% coverage)
- `gmail_client.py` (0% coverage)
- `input_validator.py` (0% coverage)
- `validator.py` (0% coverage)
