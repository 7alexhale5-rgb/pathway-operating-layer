#!/usr/bin/env bash
# Symlink the canonical pathway-operating-layer files into their live ~/.claude paths.
# Idempotent: re-running relinks anything missing or wrong. Safe on a fresh machine.
#
# The repo is canonical; ~/.claude holds only symlinks. This means an `rm` on a
# ~/.claude path drops the link, not the work — the repo copy survives.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLAUDE_HOME:-$HOME/.claude}"

# repo-relative path  ->  installs at  $CL/<same relative path>
FILES=(
  "scripts/operating-layer.py"
  "scripts/tests/operating_layer_test.py"
  "commands/pathway.md"
  "references/pathway-operating-layer.md"
)

for rel in "${FILES[@]}"; do
  src="$REPO/$rel"
  dst="$CL/$rel"
  if [[ ! -f "$src" ]]; then
    echo "MISSING in repo: $rel" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$dst")"
  # If a real (non-symlink) file is already there, refuse to clobber.
  if [[ -e "$dst" && ! -L "$dst" ]]; then
    echo "REFUSING to overwrite real file (back it up first): $dst" >&2
    exit 1
  fi
  ln -sfn "$src" "$dst"
  echo "linked  $dst -> $src"
done

echo "Done. Verify: python3 \"$CL/scripts/tests/operating_layer_test.py\""
