#!/usr/bin/env bash
# set_version.sh — Update manifest.json to match the nearest semver git tag.
#
# Usage:
#   ./scripts/set_version.sh              # reads version from git tag
#   ./scripts/set_version.sh 0.4.0       # sets version explicitly

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$SCRIPT_DIR/../custom_components/cantera/manifest.json"

if [[ $# -ge 1 ]]; then
    VERSION="$1"
else
    # Get nearest semver tag, strip leading 'v'.
    VERSION="$(git -C "$SCRIPT_DIR/.." describe --tags --abbrev=0 \
        --match '[0-9]*.[0-9]*.[0-9]*' 2>/dev/null || \
        git -C "$SCRIPT_DIR/.." describe --tags --abbrev=0 \
        --match 'v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null | sed 's/^v//' || true)"

    if [[ -z "$VERSION" ]]; then
        echo "Error: no semver git tag found. Pass the version explicitly:" >&2
        echo "  $0 0.4.0" >&2
        exit 1
    fi
fi

python3 - "$VERSION" "$MANIFEST" <<'PYEOF'
import json, pathlib, sys
version, manifest_path = sys.argv[1], pathlib.Path(sys.argv[2])
m = json.loads(manifest_path.read_text())
old = m.get("version", "?")
m["version"] = version
manifest_path.write_text(json.dumps(m, indent=2) + "\n")
print(f"manifest.json: {old} → {version}")
PYEOF
