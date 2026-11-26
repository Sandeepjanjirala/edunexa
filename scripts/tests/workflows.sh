#!/usr/bin/env bash
# Update/rollback control-flow tests with mock Git, backup and Docker functions.
set -Eeuo pipefail
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/scripts" "$work/state"
cp scripts/{update.sh,rollback.sh} "$work/scripts/"
export ROOT="$work" STATE="$work/state" CALLS="$work/calls"
cat > "$work/scripts/lib.sh" <<'EOF'
set -Eeuo pipefail
die() { echo "$*" >&2; exit 1; }
log() { :; }
load_env() { :; }
lock() { :; }
preflight() { :; }
git() {
    echo "git $*" >> "$CALLS"
    case $1 in
        status) [[ ${DIRTY:-0} == 0 ]] || echo changed ;;
        rev-parse) echo testrevision ;;
    esac
}
backup_data() { echo backup >> "$CALLS"; [[ ${BACKUP_FAIL:-0} == 0 ]]; }
release() { echo release >> "$CALLS"; }
dc() { echo "compose $*" >> "$CALLS"; }
docker() { echo "docker $*" >> "$CALLS"; }
health() { echo health >> "$CALLS"; }
EOF
expect_failure() { if "$@"; then echo 'Expected failure' >&2; exit 1; fi; }
: > "$CALLS"
expect_failure env DIRTY=1 bash "$work/scripts/update.sh"
if grep -Eq '^backup|git fetch|git merge' "$CALLS"; then exit 1; fi
: > "$CALLS"
expect_failure env BACKUP_FAIL=1 bash "$work/scripts/update.sh"
if grep -Eq 'git fetch|git merge' "$CALLS"; then exit 1; fi
: > "$CALLS"
bash "$work/scripts/update.sh" origin/main
grep -q '^backup$' "$CALLS"
grep -q '^git merge --ff-only -- origin/main$' "$CALLS"
grep -q '^release$' "$CALLS"
expect_failure bash "$work/scripts/rollback.sh"
echo sha256:test > "$STATE/previous-image"
: > "$CALLS"
bash "$work/scripts/rollback.sh" --schema-compatible
grep -q '^compose up -d --no-deps' "$CALLS"
if grep -Eq 'migrate|restore|down' "$CALLS"; then exit 1; fi
echo 'PASS: mocked dirty checkout and backup failure block fetch; clean update and explicit image-only rollback complete.'
