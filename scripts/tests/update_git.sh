#!/usr/bin/env bash
# Real Git histories, isolated repositories; deployment services are mocked.
set -Eeuo pipefail
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export GIT_AUTHOR_NAME='Updater test' GIT_COMMITTER_NAME='Updater test'
export GIT_AUTHOR_EMAIL='updater@example.invalid' GIT_COMMITTER_EMAIL='updater@example.invalid'
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
export CALLS="$work/calls"
git init -q --bare --initial-branch=main "$work/origin.git"
git clone -q "$work/origin.git" "$work/publisher"
mkdir -p "$work/publisher/scripts"
cp scripts/update.sh "$work/publisher/scripts/update.sh"
cat > "$work/publisher/scripts/lib.sh" <<'EOF'
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
STATE="$ROOT/.deploy"
die() { echo "$*" >&2; exit 1; }
log() { :; }
load_env() { mkdir -p "$STATE"; }
lock() { :; }
preflight() { :; }
backup_data() { echo backup >> "$CALLS"; echo test-backup; }
release() { git rev-parse HEAD >> "$CALLS"; }
EOF
printf '.deploy/\n' > "$work/publisher/.gitignore"
git -C "$work/publisher" add .
git -C "$work/publisher" commit -qm initial
git -C "$work/publisher" push -q origin main
git clone -q "$work/origin.git" "$work/vps"
base=$(git -C "$work/vps" rev-parse HEAD)
printf 'published change\n' > "$work/publisher/release.txt"
git -C "$work/publisher" add release.txt
git -C "$work/publisher" commit -qm release
git -C "$work/publisher" push -q origin main
published=$(git -C "$work/publisher" rev-parse HEAD)

# No upstream is necessary: no argument must fetch and deploy origin/main.
git -C "$work/vps" branch --unset-upstream
: > "$CALLS"
bash "$work/vps/scripts/update.sh"
[[ $(git -C "$work/vps" rev-parse HEAD) == "$published" ]]
[[ $(cat "$work/vps/.deploy/before-revision") == "$base" ]]
[[ $(tail -n 1 "$CALLS") == "$published" ]]
# Retrying at the same revision must still deploy (a previous release may have failed).
: > "$CALLS"
bash "$work/vps/scripts/update.sh"
[[ $(tail -n 1 "$CALLS") == "$published" ]]

expect_refusal() {
    local checkout=$1 target=${2:-origin/main} before
    before=$(git -C "$checkout" rev-parse HEAD)
    : > "$CALLS"
    if bash "$checkout/scripts/update.sh" "$target"; then
        echo 'Expected update refusal' >&2
        exit 1
    fi
    [[ $(git -C "$checkout" rev-parse HEAD) == "$before" ]]
    if grep -Eq '^[0-9a-f]{40,64}$' "$CALLS"; then exit 1; fi
}

printf 'uncommitted edit\n' >> "$work/vps/release.txt"
expect_refusal "$work/vps"
[[ ! -s "$CALLS" ]]
git -C "$work/vps" add release.txt
git -C "$work/vps" commit -qm local-only
expect_refusal "$work/vps" # Local HEAD ahead of main; --ff-only alone would accept it.

git clone -q "$work/origin.git" "$work/diverged"
printf 'local branch\n' > "$work/diverged/local.txt"
git -C "$work/diverged" add local.txt
git -C "$work/diverged" commit -qm local-branch
printf 'new upstream\n' >> "$work/publisher/release.txt"
git -C "$work/publisher" commit -qam upstream
git -C "$work/publisher" push -q origin main
expect_refusal "$work/diverged"
expect_refusal "$work/diverged" missing-revision
expect_refusal "$work/diverged" --unknown-option
[[ ! -s "$CALLS" ]]
bash "$work/diverged/scripts/update.sh" --help
[[ ! -s "$CALLS" ]]
echo 'PASS: real Git fetch/fast-forward/retry; dirty, ahead, divergent and invalid targets preserve HEAD and never deploy.'
