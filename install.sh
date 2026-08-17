#!/usr/bin/env bash
# Symlink canonical pathway files into their live Claude and Codex paths.
# Idempotent: re-running relinks anything missing or wrong. Safe on a fresh machine.
#
# The repo is canonical; agent homes hold only symlinks. Removing an installed
# link does not remove the tracked source.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CL="${CLAUDE_HOME:-$HOME/.claude}"
CX="${PATHWAY_CODEX_HOME:-$HOME/.codex}"

# repo-relative path  ->  installs at  $CL/<same relative path>
FILES=(
  "scripts/operating-layer.py"
  "scripts/tests/operating_layer_test.py"
  "commands/pathway.md"
  "references/pathway-operating-layer.md"
  "hooks/approval-issue-guard.py"
)

link_file() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "$src" ]]; then
    echo "MISSING in repo: ${src#"$REPO/"}" >&2
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
}

for rel in "${FILES[@]}"; do
  link_file "$REPO/$rel" "$CL/$rel"
done

link_file \
  "$REPO/hooks/approval-issue-guard.py" \
  "$CX/hooks/approval-issue-guard.py"

echo "Done. Verify: python3 \"$CL/scripts/tests/operating_layer_test.py\""
