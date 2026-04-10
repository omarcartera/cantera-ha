# Release Process

This document covers the release workflow for the **cantera-ha** repository
(Home Assistant custom integration).

---

## One-command release

```bash
# From the repo root, on the main branch with a clean working tree:
./scripts/release.sh           # patch bump:  0.3.0 → 0.3.1
./scripts/release.sh patch     # same as above
./scripts/release.sh minor     # minor bump:  0.3.0 → 0.4.0
./scripts/release.sh major     # major bump:  0.3.0 → 1.0.0
./scripts/release.sh 0.4.0    # explicit version
```

The script:

1. Reads the latest semver tag and computes the next version
2. Prompts for confirmation (shows branch name, tag, version)
3. Fast-forward syncs local `main` with `origin/main`
4. Creates branch `release/vX.Y.Z` off main
5. Updates `manifest.json` → `"version": "X.Y.Z"` via `scripts/set_version.sh`
6. Commits the version bump with a `chore: release X.Y.Z` message
7. Creates annotated tag `vX.Y.Z`
8. Pushes the branch and tag to origin
9. Creates a GitHub release (marked as latest) with auto-generated release notes
10. Prints the release URL

---

## What CI does on tag push

`.github/workflows/release.yml` triggers on `vX.Y.Z` / `X.Y.Z` tags:

- Verifies `manifest.json` version matches the tag (updates it if not, commits back to main)
- Creates a GitHub release with auto-generated notes if one does not already exist

> The script creates the release first, so CI's release step is a no-op in the
> normal flow. CI acts as a safety net when tagging manually.

---

## Manual version bump only

```bash
./scripts/set_version.sh             # reads version from nearest semver git tag
./scripts/set_version.sh 0.4.0      # explicit version
```

---

## Version source

The version shown in Home Assistant comes from `manifest.json` → `"version"`.
This file is updated automatically by `scripts/release.sh` and the CI workflow
on every tag push. It is **never edited by hand**.

---

## Version numbering

```
MAJOR . MINOR . PATCH
  │       │       └── Bug fixes, small improvements (most releases)
  │       └────────── New features, non-breaking changes
  └────────────────── Breaking changes (config schema, coordinator API)
```

### Pre-release tags

Append a suffix for beta/RC builds:

```bash
git tag -a v0.4.0-rc.1 -m "Release candidate 1"
git push origin v0.4.0-rc.1
```

---

## What HACS sees

HACS reads `manifest.json` → `version` from the tagged commit. After a release:

1. Users with the integration installed see a HACS update notification
2. Clicking **Update** downloads the tagged commit and replaces the files on disk
3. Home Assistant restart is required — Python modules are not reimported until
   HA restarts, so a reload alone does not activate the new code

The integration's built-in update entity follows the same approach: it downloads
and installs the files, then shows a persistent notification asking the user to
restart Home Assistant.

---

## Release checklist

- [ ] All tests pass: `python3 -m pytest tests/ -v`
- [ ] Linter clean: `ruff check custom_components/cantera/`
- [ ] Type check clean: `mypy custom_components/cantera/ --ignore-missing-imports`
- [ ] On `main` branch, clean working tree
- [ ] Run `./scripts/release.sh [patch|minor|major|X.Y.Z]`
- [ ] Verify GitHub release appears and HACS picks it up

---

## Rollback

HACS allows downgrading to a specific version:

**HACS → CANtera OBD-II → ⋮ → Redownload → pick version**
