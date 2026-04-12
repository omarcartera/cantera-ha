#!/usr/bin/env bash
# release.sh — Full GitHub release automation for cantera-ha.
#
# Usage:
#   ./scripts/release.sh               # auto-bumps patch (0.3.0 → 0.3.1)
#   ./scripts/release.sh patch         # same as above
#   ./scripts/release.sh minor         # 0.3.0 → 0.4.0
#   ./scripts/release.sh major         # 0.3.0 → 1.0.0
#   ./scripts/release.sh 0.4.0        # explicit version
#
# What it does:
#   1. Determine the next version (from latest semver tag + bump type)
#   2. Ensure local main is up to date with origin
#   3. Create release/vX.Y.Z branch off main
#   4. Update manifest.json via set_version.sh
#   5. Commit the version bump
#   6. Create and push the tag vX.Y.Z
#   7. Push the release branch
#   8. Create a GitHub release (marked as latest) with auto-generated notes

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "→ Switching to main and pulling latest..."
git checkout main
git pull --ff-only origin main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() { echo "❌ $*" >&2; exit 1; }
info() { echo "  $*"; }
step() { echo; echo "▶ $*"; }

require_clean_main() {
    local current_branch
    current_branch="$(git rev-parse --abbrev-ref HEAD)"
    if [[ "$current_branch" != "main" ]]; then
        die "Must be on 'main' to cut a release (currently on '$current_branch')"
    fi
    if ! git diff --quiet || ! git diff --cached --quiet; then
        die "Working tree is dirty — commit or stash your changes first"
    fi
}

latest_semver_tag() {
    git tag --sort=-version:refname \
        | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' \
        | head -1 \
        | sed 's/^v//'
}

bump_version() {
    local current="$1" bump="$2"
    local major minor patch
    IFS='.' read -r major minor patch <<< "$current"
    case "$bump" in
        major) echo "$((major + 1)).0.0" ;;
        minor) echo "${major}.$((minor + 1)).0" ;;
        patch) echo "${major}.${minor}.$((patch + 1))" ;;
        *)     die "Unknown bump type: $bump (use major|minor|patch)" ;;
    esac
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

BUMP_TYPE="patch"
EXPLICIT_VERSION=""

if [[ $# -ge 1 ]]; then
    case "$1" in
        major|minor|patch) BUMP_TYPE="$1" ;;
        [0-9]*.[0-9]*.[0-9]*)
            EXPLICIT_VERSION="${1#v}"   # strip leading v if present
            ;;
        *) die "Unknown argument: $1\nUsage: $0 [major|minor|patch|X.Y.Z]" ;;
    esac
fi

# ---------------------------------------------------------------------------
# Determine version
# ---------------------------------------------------------------------------

step "Determining version"

CURRENT_VERSION="$(latest_semver_tag)"
if [[ -z "$CURRENT_VERSION" ]]; then
    info "No existing semver tag found — starting from 0.1.0"
    CURRENT_VERSION="0.0.0"
fi
info "Current version : v${CURRENT_VERSION}"

if [[ -n "$EXPLICIT_VERSION" ]]; then
    NEXT_VERSION="$EXPLICIT_VERSION"
else
    NEXT_VERSION="$(bump_version "$CURRENT_VERSION" "$BUMP_TYPE")"
fi
info "Next version    : v${NEXT_VERSION}"

BRANCH="release/v${NEXT_VERSION}"
TAG="v${NEXT_VERSION}"

# Guard: don't overwrite an existing tag.
if git rev-parse "$TAG" &>/dev/null; then
    die "Tag $TAG already exists — pick a different version or delete the tag first"
fi

# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

echo
echo "  Release summary:"
echo "    Version : ${NEXT_VERSION}"
echo "    Branch  : ${BRANCH}"
echo "    Tag     : ${TAG}"
echo
read -r -p "  Proceed? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

# ---------------------------------------------------------------------------
# Sync main
# ---------------------------------------------------------------------------

step "Syncing main with origin"
require_clean_main
git fetch origin main --prune
git merge --ff-only origin/main
info "main is up to date with origin/main"

# ---------------------------------------------------------------------------
# Create release branch
# ---------------------------------------------------------------------------

step "Creating branch ${BRANCH}"
git checkout -b "$BRANCH"
info "On branch $BRANCH"

# ---------------------------------------------------------------------------
# Update manifest.json
# ---------------------------------------------------------------------------

step "Updating manifest.json to ${NEXT_VERSION}"
bash scripts/set_version.sh "$NEXT_VERSION"

# ---------------------------------------------------------------------------
# Commit version bump
# ---------------------------------------------------------------------------

step "Committing version bump"
git add custom_components/cantera/manifest.json
if git diff --cached --quiet; then
    info "manifest.json already at ${NEXT_VERSION} — skipping commit"
else
    git commit -m "chore: release ${NEXT_VERSION}

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
    info "Committed version bump"
fi

# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------

step "Tagging ${TAG}"
git tag -a "$TAG" -m "Release ${NEXT_VERSION}"
info "Created annotated tag ${TAG}"

# ---------------------------------------------------------------------------
# Push branch and tag
# ---------------------------------------------------------------------------

step "Pushing ${BRANCH} and ${TAG} to origin"
git push -u origin "$BRANCH"
git push origin "$TAG"
info "Pushed branch and tag"

# ---------------------------------------------------------------------------
# Create GitHub release
# ---------------------------------------------------------------------------

step "Creating GitHub release ${TAG}"
gh release create "$TAG" \
    --title "Release ${NEXT_VERSION}" \
    --generate-notes \
    --latest \
    --target "$BRANCH"

echo
echo "✅  Release ${NEXT_VERSION} is live!"
echo "    Branch : ${BRANCH}"
echo "    Tag    : ${TAG}"
echo "    URL    : $(gh release view "$TAG" --json url -q .url)"
