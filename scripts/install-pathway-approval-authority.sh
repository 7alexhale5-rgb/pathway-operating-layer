#!/bin/sh
# Root-owned second stage for the Pathway approval authority trust ceremony.
#
# NEVER run this mutable repository copy with sudo. First use only fixed Apple
# tools to copy the reviewed bytes into a root-owned staging directory, verify
# those staged bytes against the human-reviewed digests, then execute the
# staged installer. Replace <INSTALLER_SHA256> with the digest published beside
# the reviewed change; the helper digest is pinned below.
#
#   /usr/bin/sudo -k
#   /usr/bin/sudo /usr/bin/install -d -o root -g wheel -m 0700 /private/var/root/pathway-approval-bootstrap
#   /usr/bin/sudo /usr/bin/install -o root -g wheel -m 0500 /Users/alexhale/Projects/pathway-operating-layer/scripts/install-pathway-approval-authority.sh /private/var/root/pathway-approval-bootstrap/install.sh
#   /usr/bin/sudo /usr/bin/install -o root -g wheel -m 0500 /Users/alexhale/Projects/pathway-operating-layer/security/pathway-approval /private/var/root/pathway-approval-bootstrap/pathway-approval
#   /usr/bin/printf '%s  %s\n' '<INSTALLER_SHA256>' '/private/var/root/pathway-approval-bootstrap/install.sh' | /usr/bin/sudo /usr/bin/shasum -a 256 -c -
#   /usr/bin/printf '%s  %s\n' '34df494a986a2b56e056190b507e6117fae70a979135418517b311f116e3e323' '/private/var/root/pathway-approval-bootstrap/pathway-approval' | /usr/bin/sudo /usr/bin/shasum -a 256 -c -
#   /usr/bin/sudo /private/var/root/pathway-approval-bootstrap/install.sh --expected-installer-sha256 '<INSTALLER_SHA256>' --expected-helper-sha256 '34df494a986a2b56e056190b507e6117fae70a979135418517b311f116e3e323'
#
# No project-owned code executes as root before both staged hashes match. The
# staged directory is preserved as a root-owned audit artifact. Steady-state OS
# separation begins only after this staged installer bootstraps the authority
# ledger and validates the final installed copy.

set -eu
umask 077
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH

STAGE_DIR="/private/var/root/pathway-approval-bootstrap"
STAGED_INSTALLER="$STAGE_DIR/install.sh"
STAGED_HELPER="$STAGE_DIR/pathway-approval"
PINNED_HELPER_SHA256="34df494a986a2b56e056190b507e6117fae70a979135418517b311f116e3e323"
INSTALL_DIR="/usr/local/libexec"
INSTALL_HELPER="$INSTALL_DIR/pathway-approval"
AUTHORITY_DIR="/Library/Application Support/Pathway"
AUTHORITY_LEDGER="$AUTHORITY_DIR/approval-authority.ndjson"
SUDOERS_PATH="/etc/sudoers.d/pathway-approval"
LEGACY_LEDGER="/Users/alexhale/Projects/memory-vault/operator-intelligence/approvals.ndjson"
LEGACY_SHA256="37b067ab41a9775769fce89ba1371171642a274c6cb6614a0f369a7636ba2a99"
LEGACY_REJECT_REASON="Legacy user-owned approval history is audit evidence only; independent human authorization was not established."

fail() {
  /usr/bin/printf '%s\n' "ERROR: $*" >&2
  exit 1
}

digest_of() {
  /usr/bin/shasum -a 256 -- "$1" | /usr/bin/awk '{print $1}'
}

require_staged_file() {
  path=$1
  [ -f "$path" ] && [ ! -L "$path" ] || fail "staged trust file is missing, non-regular, or symlinked"
  [ "$(/usr/bin/stat -f '%u' -- "$path")" = "0" ] || fail "staged trust file must be root-owned"
  [ "$(/usr/bin/stat -f '%g' -- "$path")" = "0" ] || fail "staged trust file must be wheel-grouped"
  [ "$(/usr/bin/stat -f '%Lp' -- "$path")" = "500" ] || fail "staged trust file must be mode 0500"
}

[ "$(/usr/bin/id -u)" -eq 0 ] || fail "run only the verified root-owned staged installer through sudo"
[ -n "${SUDO_USER:-}" ] || fail "SUDO_USER is required; direct root execution is refused"
[ -n "${SUDO_UID:-}" ] || fail "SUDO_UID is required; direct root execution is refused"
[ "$#" -eq 4 ] || fail "pass exact --expected-installer-sha256 and --expected-helper-sha256 values"
[ "$1" = "--expected-installer-sha256" ] || fail "first argument must be --expected-installer-sha256"
EXPECTED_INSTALLER_SHA256=$2
[ "$3" = "--expected-helper-sha256" ] || fail "third argument must be --expected-helper-sha256"
EXPECTED_HELPER_SHA256=$4

case "$EXPECTED_INSTALLER_SHA256:$EXPECTED_HELPER_SHA256" in
  *[!0-9a-f:]*|'') fail "expected digests must be lowercase hexadecimal" ;;
esac
[ "${#EXPECTED_INSTALLER_SHA256}" -eq 64 ] || fail "installer digest must be 64 lowercase hex characters"
[ "${#EXPECTED_HELPER_SHA256}" -eq 64 ] || fail "helper digest must be 64 lowercase hex characters"
[ "$EXPECTED_HELPER_SHA256" = "$PINNED_HELPER_SHA256" ] || fail "helper digest does not match the reviewed build"

case "$SUDO_USER" in
  [A-Za-z_]*) ;;
  *) fail "SUDO_USER contains characters unsafe for a sudoers principal" ;;
esac
case "$SUDO_USER" in
  *[!A-Za-z0-9_.-]*) fail "SUDO_USER contains characters unsafe for a sudoers principal" ;;
esac
case "$SUDO_UID" in
  *[!0-9]*|'') fail "SUDO_UID must be numeric" ;;
esac
[ "$SUDO_UID" -gt 0 ] || fail "the invoking sudo user must be non-root"
[ "$(/usr/bin/id -u "$SUDO_USER")" = "$SUDO_UID" ] || fail "SUDO_USER and SUDO_UID do not match"

[ "$(CDPATH= cd -- "$(/usr/bin/dirname -- "$0")" && /bin/pwd -P)" = "$STAGE_DIR" ] \
  || fail "refusing to execute outside the fixed root-owned staging directory"
[ -d "$STAGE_DIR" ] && [ ! -L "$STAGE_DIR" ] || fail "staging directory is missing or symlinked"
[ "$(/usr/bin/stat -f '%u' -- "$STAGE_DIR")" = "0" ] || fail "staging directory must be root-owned"
[ "$(/usr/bin/stat -f '%g' -- "$STAGE_DIR")" = "0" ] || fail "staging directory must be wheel-grouped"
[ "$(/usr/bin/stat -f '%Lp' -- "$STAGE_DIR")" = "700" ] || fail "staging directory must be mode 0700"
require_staged_file "$STAGED_INSTALLER"
require_staged_file "$STAGED_HELPER"
[ "$(digest_of "$STAGED_INSTALLER")" = "$EXPECTED_INSTALLER_SHA256" ] || fail "staged installer digest mismatch"
[ "$(digest_of "$STAGED_HELPER")" = "$EXPECTED_HELPER_SHA256" ] || fail "staged helper digest mismatch"
[ -x /usr/sbin/visudo ] || fail "visudo is required"

/usr/bin/install -d -o root -g wheel -m 0755 "$INSTALL_DIR"
/usr/bin/install -d -o root -g wheel -m 0755 "$AUTHORITY_DIR"
/usr/bin/install -o root -g wheel -m 0755 "$STAGED_HELPER" "$INSTALL_HELPER"
[ "$(digest_of "$INSTALL_HELPER")" = "$EXPECTED_HELPER_SHA256" ] || fail "final installed helper digest mismatch"

if [ -L "$AUTHORITY_LEDGER" ]; then
  fail "authority ledger is a symlink"
fi
if [ ! -e "$AUTHORITY_LEDGER" ]; then
  /usr/bin/install -o root -g wheel -m 0644 /dev/null "$AUTHORITY_LEDGER"
fi

# Import the exact reviewed 41-row legacy snapshot before exposing any issue or
# invalidate command through sudoers. Rejected consumed rows remain as history;
# every legacy issued ticket receives an appended invalidation. New authority
# must be issued afresh through the installed root-owned helper.
"$INSTALL_HELPER" bootstrap \
  --source-ledger "$LEGACY_LEDGER" \
  --expected-sha256 "$LEGACY_SHA256" \
  --invalidate-all-issued \
  --reason "$LEGACY_REJECT_REASON"
"$INSTALL_HELPER" verify >/dev/null

SUDOERS_TEMP=$(/usr/bin/mktemp "/tmp/pathway-approval-sudoers.XXXXXX")
cleanup() {
  /bin/rm -f -- "$SUDOERS_TEMP"
}
trap cleanup EXIT HUP INT TERM

{
  /usr/bin/printf '%s\n' 'Defaults!/usr/local/libexec/pathway-approval timestamp_timeout=0'
  /usr/bin/printf '%s\n' "$SUDO_USER ALL = (root) PASSWD: NOSETENV: /usr/local/libexec/pathway-approval *"
} > "$SUDOERS_TEMP"
/bin/chmod 0440 "$SUDOERS_TEMP"
/usr/sbin/visudo -cf "$SUDOERS_TEMP" >/dev/null
/usr/bin/install -o root -g wheel -m 0440 "$SUDOERS_TEMP" "$SUDOERS_PATH"
/usr/sbin/visudo -cf "$SUDOERS_PATH" >/dev/null

/usr/bin/printf '%s\n' "Installed verified root-owned authority: $INSTALL_HELPER"
/usr/bin/printf '%s\n' "Installed root-owned ledger: $AUTHORITY_LEDGER"
/usr/bin/printf '%s\n' "Bootstrapped exact 41-row legacy ledger with every legacy issuance invalidated: $LEGACY_SHA256"
/usr/bin/printf '%s\n' "Installed password-required sudo rule: $SUDOERS_PATH"
/usr/bin/printf '%s\n' 'Every later authority action must start a fresh sudo authentication:'
/usr/bin/printf '%s\n' '  /usr/bin/sudo -k; /usr/bin/sudo /usr/local/libexec/pathway-approval verify'
/usr/bin/printf '%s\n' "Preserved root-owned bootstrap audit files: $STAGE_DIR"
