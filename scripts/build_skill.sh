#!/usr/bin/env bash
# 把 causpec 构建成 wheel 放进 skill 的 assets，然后打包整个 skill。
#
# wheel 是构建产物，不入库——入库的 wheel 会和源码悄悄脱节，
# 而 skill 在 claude.ai 上跑的正是这个 wheel。每次打包前重新构建。
set -euo pipefail

cd "$(dirname "$0")/.."
SKILL_DIR="skill/causpec-analyst"

echo "构建 wheel…"
rm -f "$SKILL_DIR/assets/"*.whl
uv build --wheel
cp dist/causpec-*.whl "$SKILL_DIR/assets/"

WHEEL=$(basename "$SKILL_DIR/assets/"causpec-*.whl)
echo "  → $SKILL_DIR/assets/$WHEEL"

echo "打包 skill…"
OUT="dist/causpec-analyst-skill.zip"
rm -f "$OUT"
(cd skill && zip -qr "../$OUT" causpec-analyst -x '*/__pycache__/*')
echo "  → $OUT  ($(du -h "$OUT" | cut -f1))"

echo
echo "自检："
uv run python "$SKILL_DIR/scripts/run.py" --version
