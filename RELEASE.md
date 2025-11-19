# Release Process

This document describes the proper workflow for creating releases of Gmail Archiver.

## Prerequisites

- All tests passing on main branch
- CHANGELOG.md updated with version entry
- PyPI token configured in GitHub secrets (`PYPI_TOKEN`)

## Release Workflow

### 1. Prepare the Release

**Update CHANGELOG.md:**

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New features

### Changed
- Changes to existing functionality

### Fixed
- Bug fixes
```

**Commit the changelog:**

```bash
git add CHANGELOG.md
git commit -m "docs: Prepare v1.1.4 release"
git push origin main
```

### 2. Create and Push the Tag

**IMPORTANT**: The tag must be created on the **latest commit** of the main branch. If there are commits after the tag, the build will create a development version instead of a release version.

```bash
# Ensure you're on the latest main
git checkout main
git pull origin main

# Verify tests pass
uv run pytest

# Verify code quality
uv run ruff check .
uv run mypy src/gmailarchiver

# Create the tag (replace X.Y.Z with actual version)
git tag vX.Y.Z

# Push the tag to trigger the release workflow
git push origin vX.Y.Z
```

### 3. Automated Build and Publish

The `release-and-publish.yml` workflow automatically:

1. ✅ Checks out code at the exact tag
2. ✅ Builds the package
3. ✅ **Verifies** the built version matches the tag (fails if mismatch)
4. ✅ Creates GitHub release with assets
5. ✅ Publishes to PyPI
6. ✅ Verifies PyPI publication

### 4. Verify the Release

**Check GitHub Release:**
- Go to https://github.com/tumma72/GMailArchiver/releases
- Verify the assets have correct version (not `.dev0`)
- Example: `gmail_archiver_cli-1.1.4-py3-none-any.whl` (NOT `1.1.5.dev0+...`)

**Check PyPI:**
```bash
pip index versions gmail-archiver-cli
```

**Test installation:**
```bash
pip install --upgrade gmail-archiver-cli==X.Y.Z
gmailarchiver --version
```

## Common Issues

### Issue: Built version doesn't match tag

**Error message:**
```
❌ ERROR: Built version (1.1.5.dev0+g1234567) does not match tag version (1.1.4)
This usually means there are commits after the tag.
```

**Cause:** There are commits on the main branch after the tag.

**Solution:**
```bash
# Delete the remote tag
git push origin --delete vX.Y.Z

# Delete the local tag
git tag -d vX.Y.Z

# Ensure you're on latest main
git pull origin main

# Create the tag again on the latest commit
git tag vX.Y.Z

# Push the tag
git push origin vX.Y.Z
```

### Issue: Need to fix something in a released version

**If the release hasn't been published yet:**
1. Delete the tag (see above)
2. Make your fixes
3. Commit and push
4. Create the tag again on the latest commit

**If the release has already been published:**
1. Make your fixes
2. Bump the version number (e.g., 1.1.4 → 1.1.5)
3. Follow the normal release process for the new version

## Version Numbering

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (X.0.0): Incompatible API changes
- **MINOR** (1.X.0): New functionality, backwards compatible
- **PATCH** (1.1.X): Bug fixes, backwards compatible

## Release Checklist

- [ ] All tests passing (`uv run pytest`)
- [ ] Code quality checks passing (`uv run ruff check .` && `uv run mypy src/gmailarchiver`)
- [ ] CHANGELOG.md updated with version entry
- [ ] Changes committed and pushed to main
- [ ] On latest commit of main branch
- [ ] Tag created: `git tag vX.Y.Z`
- [ ] Tag pushed: `git push origin vX.Y.Z`
- [ ] GitHub Actions workflow succeeded
- [ ] GitHub release created with correct version
- [ ] PyPI package published with correct version
- [ ] Verified installation: `pip install gmail-archiver-cli==X.Y.Z`

## Emergency: Deleting a Bad Release

**GitHub Release:**
```bash
gh release delete vX.Y.Z --yes
git push origin --delete vX.Y.Z
git tag -d vX.Y.Z
```

**PyPI Release:**

PyPI releases cannot be deleted, but you can:
1. Yank the release (makes it unavailable for new installs):
   ```bash
   pip install twine
   twine upload --skip-existing dist/*  # Re-upload doesn't work
   # Contact PyPI support to yank or use the web interface
   ```

2. Immediately release a fixed version with a bumped version number

**Best practice**: Always verify builds before releasing to production.
