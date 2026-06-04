#!/usr/bin/env bash
# Spec 54 — bump version semver (sync pyproject + package.json).
#
# Uso:
#   scripts/bump.sh patch   # 0.1.0 → 0.1.1
#   scripts/bump.sh minor   # 0.1.0 → 0.2.0
#   scripts/bump.sh major   # 0.1.0 → 1.0.0
#
# Edita os 2 arquivos + stage no git. Não commita nem cria tag — você
# decide quando depois (`git commit -m "..." && git tag vX.Y.Z`).
set -euo pipefail

PART=${1:-}
if [[ "$PART" != "patch" && "$PART" != "minor" && "$PART" != "major" ]]; then
  echo "Uso: $0 patch|minor|major" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYPROJECT="$REPO_ROOT/pyproject.toml"
PKG="$REPO_ROOT/frontend/package.json"

CUR=$(grep -m1 '^version = ' "$PYPROJECT" | cut -d'"' -f2)
IFS='.' read -r MAJ MIN PAT <<< "$CUR"

case "$PART" in
  major) MAJ=$((MAJ+1)); MIN=0; PAT=0 ;;
  minor) MIN=$((MIN+1)); PAT=0 ;;
  patch) PAT=$((PAT+1)) ;;
esac
NEW="$MAJ.$MIN.$PAT"

# pyproject.toml
sed -i.bak "s/^version = .*/version = \"$NEW\"/" "$PYPROJECT"
rm "$PYPROJECT.bak"

# frontend/package.json
node -e "
const fs = require('fs');
const p = require('$PKG');
p.version = '$NEW';
fs.writeFileSync('$PKG', JSON.stringify(p, null, 2) + '\n');
"

git -C "$REPO_ROOT" add pyproject.toml frontend/package.json

echo "Bumped $CUR → $NEW"
echo "Next: git commit -m \"chore: bump v$NEW\" && git tag v$NEW"
