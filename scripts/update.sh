#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
[[ $# -le 1 ]] || die 'Usage: bash scripts/update.sh [origin/main or approved revision]'
load_env
lock
preflight
[[ -z $(git status --porcelain) ]] || die 'Local changes detected. Commit or preserve them deliberately before updating.'
git rev-parse HEAD > "$STATE/before-revision"
backup_data > "$STATE/latest-backup"
git fetch origin
target=${1:-'@{upstream}'}
git rev-parse --verify --end-of-options "$target^{commit}" >/dev/null || die 'Choose an existing fetched revision, for example origin/main.'
git merge --ff-only -- "$target"
# Reload updated functions without dropping the deployment lock.
source "$ROOT/scripts/lib.sh"
load_env
preflight
release
