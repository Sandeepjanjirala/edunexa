#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
usage() {
    cat <<'EOF'
Usage: bash scripts/update.sh [origin/main or approved revision]

Default: origin/main. Run in the existing host-Nginx VPS checkout.
Creates backups, fetches GitHub, fast-forwards, builds, migrates, restarts
web/worker/beat and verifies health including HTTPS. Expect a maintenance window.
Keeps the existing .env and Compose project. Refuses local changes or commits
absent from the target. Does not reset Git, replace credentials or delete volumes.
Run again to retry a failed deployment, even if Git is already up to date.
EOF
}
[[ $# -le 1 ]] || { usage >&2; exit 1; }
case ${1:-} in
    -h|--help) usage; exit 0 ;;
    -*) usage >&2; exit 1 ;;
esac
target=${1:-origin/main}
load_env
lock
preflight
[[ -z $(git status --porcelain) ]] || die 'Local changes detected. Commit or preserve them deliberately before updating.'
git rev-parse HEAD > "$STATE/before-revision"
log "Creating a backup before updating to $target. Keep this terminal open until deployment succeeds."
backup_data > "$STATE/latest-backup"
git fetch origin
target_revision=$(git rev-parse --verify --end-of-options "$target^{commit}") || die 'Choose an existing fetched revision, for example origin/main.'
# --ff-only also succeeds when HEAD is ahead of the target; that must not deploy
# local-only commits while claiming to update to the published revision.
git merge-base --is-ancestor HEAD "$target_revision" || die 'Local HEAD contains commits absent from the target. Reconcile the history deliberately, then retry; nothing was reset or deployed.'
log "Updating $(git rev-parse --short HEAD) to $target_revision ($target)."
git merge --ff-only -- "$target_revision"
# Reload updated functions without dropping the deployment lock.
source "$ROOT/scripts/lib.sh"
load_env
preflight
release
log "Update complete at $(git rev-parse --short=12 HEAD). Refresh your browser to load the new interface."
