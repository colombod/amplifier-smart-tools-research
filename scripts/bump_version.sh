#!/usr/bin/env bash
# scripts/bump_version.sh NEW_VERSION [--venv PATH]
#
# WHY THIS EXISTS
# ----------------
# One version number has to agree across SEVEN files (see scripts/preflight.sh
# for the full list and the incident that made this worth automating). Seven
# independent hand-edits is hidden state: nothing stops a human -- or an
# agent -- from doing four of them and calling it done, which is exactly
# what happened across 004a623 / c128f7e / d0a80da.
#
# THE DECISION THIS SCRIPT RECORDS
# ---------------------------------
# packages/research-core/pyproject.toml carries a comment explaining why its
# version is STATIC rather than dynamic (`[tool.hatch.version] source = ...`):
# a dynamic version makes the conformance kit's `manifest-version-matches-package`
# rule report SKIP instead of FAIL when it can't statically resolve a value,
# which is a real check silently lost. That comment is correct and this
# script does not fight it -- every file this script writes still ends up
# with a plain, static, literal version string. What changes is WHO edits it:
# a human runs this script once with the new version; the script is the only
# thing that hand-edits the seven files below. The duplication is still
# there on disk (a conformance-kit requirement, not a choice), but it is no
# longer duplicated EFFORT, and scripts/preflight.sh still independently
# verifies all seven agree, so a hand-edit that bypasses this script (or a
# merge conflict that reintroduces drift) is still caught before it reaches CI.
#
# WHAT IT TOUCHES
#   VERSION                                              (new canonical source)
#   packages/research-core/pyproject.toml                 [project].version
#   tools/deep-research/pyproject.toml                    [project].version
#   tools/fact-check/pyproject.toml                       [project].version
#   tools/deep-research/src/deep_research/SMART_TOOL.md    version: frontmatter
#   tools/fact-check/src/fact_check/SMART_TOOL.md          version: frontmatter
#   skills/deep-research/SKILL.md                          regenerated
#   skills/fact-check/SKILL.md                             regenerated
#
# The regeneration step (and the self-check at the end) needs research-core
# and both tools importable, so it reinstalls them editable into --venv
# (default: .venv at the repo root) after the text edits land. Create that
# venv first (see CONTRIBUTING.md) if it does not already exist.
#
# USAGE
#   scripts/bump_version.sh 0.11.0
#   scripts/bump_version.sh 0.11.0 --venv /path/to/venv
#
# This script only EDITS FILES and reinstalls into the venv you point it at.
# It never touches git. Review the diff, then commit it yourself.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

NEW_VERSION="${1:-}"
VENV="$REPO_DIR/.venv"

if [ -z "$NEW_VERSION" ]; then
  echo "usage: $0 NEW_VERSION [--venv PATH]" >&2
  exit 2
fi
shift
while [ $# -gt 0 ]; do
  case "$1" in
    --venv) VENV="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([ab][0-9]+|rc[0-9]+)?$ ]]; then
  echo "refusing: '$NEW_VERSION' does not look like a version (expected e.g. 1.2.3)" >&2
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "refusing: no venv at $VENV (create one per CONTRIBUTING.md, or pass --venv)" >&2
  exit 1
fi

PYPROJECTS=(
  packages/research-core/pyproject.toml
  tools/deep-research/pyproject.toml
  tools/fact-check/pyproject.toml
)
MANIFESTS=(
  tools/deep-research/src/deep_research/SMART_TOOL.md
  tools/fact-check/src/fact_check/SMART_TOOL.md
)

echo "=== writing VERSION ==="
echo "$NEW_VERSION" > VERSION

echo "=== updating pyproject.toml [project].version (static string, not dynamic) ==="
for f in "${PYPROJECTS[@]}"; do
  if ! grep -qE '^version = "[^"]+"' "$f"; then
    echo "refusing: $f has no 'version = \"...\"' line to replace -- edit it by hand" >&2
    exit 1
  fi
  sed -i -E "s/^version = \"[^\"]+\"/version = \"${NEW_VERSION}\"/" "$f"
  echo "  $f -> $NEW_VERSION"
done

echo "=== updating SMART_TOOL.md 'version:' frontmatter ==="
for f in "${MANIFESTS[@]}"; do
  if ! grep -qE '^version: .+$' "$f"; then
    echo "refusing: $f has no 'version: ...' frontmatter line -- edit it by hand" >&2
    exit 1
  fi
  sed -i -E "s/^version: .+$/version: ${NEW_VERSION}/" "$f"
  echo "  $f -> $NEW_VERSION"
done

echo "=== reinstalling into $VENV so dist-info matches the new pyproject.toml files ==="
uv pip install --python "$VENV/bin/python" -e packages/research-core -q
uv pip install --python "$VENV/bin/python" --no-deps \
  -e tools/deep-research -e tools/fact-check -q

echo "=== regenerating skills/*/SKILL.md from pointer_skill() ==="
"$VENV/bin/python" -c "
import deep_research, pathlib
pathlib.Path('skills/deep-research/SKILL.md').write_text(deep_research.pointer_skill(), encoding='utf-8')
"
"$VENV/bin/python" -c "
import fact_check, pathlib
pathlib.Path('skills/fact-check/SKILL.md').write_text(fact_check.pointer_skill(), encoding='utf-8')
"
echo "  skills/deep-research/SKILL.md, skills/fact-check/SKILL.md regenerated"

echo "=== self-check: do all seven files agree, and does the installed metadata agree too? ==="
if ! "$VENV/bin/python" -m pytest -q \
      packages/research-core/tests/test_manifest.py -k version_matches_package_version \
      packages/research-core/tests/test_skill.py -k committed_skill_file_matches; then
  echo "self-check FAILED -- do not commit this state" >&2
  exit 1
fi

echo ""
echo "all seven files now say $NEW_VERSION. Review the diff, then commit it yourself."
echo "(this script never runs git)"
