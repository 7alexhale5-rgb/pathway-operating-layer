#!/usr/bin/env bash
# Avoid Python startup only when the raw JSON cannot contain an approval command.
# Any escape or shell single quote takes the full parser path. Never eval input.
IFS= read -r -d '' payload || :
case "$payload" in
  *\\*|*"'"*|*[aA][pP][pP][rR][oO][vV][aA][lL]*)
    printf '%s' "$payload" | python3 -S "$(dirname "$0")/approval-issue-guard.py"
    exit $? ;;
  *) exit 0 ;;
esac
