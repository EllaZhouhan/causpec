#!/usr/bin/env bash
# Build causpec into a wheel, place it in the skill's assets, and package the skill.
#
# The wheel is a build product and is not committed: a committed wheel drifts silently
# from the source, and the wheel is exactly what the skill runs. Rebuild before every
# package.
set -euo pipefail

cd "$(dirname "$0")/.."
SKILL_DIR="skill/causpec-analyst"

echo "Building the wheel..."
rm -f "$SKILL_DIR/assets/"*.whl
uv build --wheel
cp dist/causpec-*.whl "$SKILL_DIR/assets/"

WHEEL=$(basename "$SKILL_DIR/assets/"causpec-*.whl)
echo "  -> $SKILL_DIR/assets/$WHEEL"

echo "Packaging the skill..."
OUT="dist/causpec-analyst-skill.zip"
rm -f "$OUT"
(cd skill && zip -qr "../$OUT" causpec-analyst -x '*/__pycache__/*')
echo "  -> $OUT  ($(du -h "$OUT" | cut -f1))"

echo
echo "Self-check:"
uv run python "$SKILL_DIR/scripts/run.py" --version
