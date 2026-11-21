#!/bin/sh
# Make the causpec-analyst skill visible to every agent harness on this machine.
#
#   git clone https://github.com/EllaZhouhan/causpec.git && sh causpec/install.sh
#
# The clone lands in the current directory, so that is where CauSpec lives. The script works
# from wherever it is run, since it resolves its own location.
#
# Each harness reads personal skills from its own folder, so the skill gets one symlink per
# harness, all pointing at this clone. A link rather than a copy, so a `git pull` reaches
# every harness at once. Nothing Python is installed here: the agent installs the library the
# first time it needs it, and asks before it does.
#
# Safe to run again. An existing link is replaced; a real folder in the way is left alone.

set -eu

clone=$(cd "$(dirname "$0")" && pwd -P)
skill="$clone/skill/causpec-analyst"

if [ ! -f "$skill/SKILL.md" ]; then
    echo "Cannot find the skill at $skill. Run this script from inside a causpec clone." >&2
    exit 1
fi

# One line per harness: its name, the command it installs, its config folder, and the folder
# it reads personal skills from. A harness counts as installed if either of the first two
# exists. To support another harness, add a line.
harnesses="Claude Code|claude|$HOME/.claude|$HOME/.claude/skills
Codex|codex|$HOME/.codex|$HOME/.agents/skills"

link() {
    name=$1
    dir=$2
    target="$dir/causpec-analyst"
    if [ -e "$target" ] && [ ! -L "$target" ]; then
        echo "  $name: skipped, $target is a real folder rather than a link. Move it away and run this again."
        return
    fi
    mkdir -p "$dir"
    ln -sfn "$skill" "$target"
    echo "  $name: $target"
}

echo "Linking the CauSpec skill for:"
found=0
old_ifs=$IFS
IFS='
'
for line in $harnesses; do
    IFS='|' read -r name cmd config dir <<EOF
$line
EOF
    if command -v "$cmd" >/dev/null 2>&1 || [ -d "$config" ]; then
        link "$name" "$dir"
        found=1
    fi
done

# Neither harness is installed yet. Link for both, so whichever is installed later finds it.
if [ "$found" -eq 0 ]; then
    for line in $harnesses; do
        IFS='|' read -r name cmd config dir <<EOF
$line
EOF
        link "$name" "$dir"
    done
    echo "Neither Claude Code nor Codex was found, so the skill is linked for both."
fi
IFS=$old_ifs

if ! command -v uv >/dev/null 2>&1; then
    echo
    echo "One more thing: uv is not installed, and the agent needs it to install CauSpec's code."
    echo "Install it from https://docs.astral.sh/uv/getting-started/installation/"
fi

echo
echo "Done. CauSpec is in $clone. Keep it there, since the links point to it."
