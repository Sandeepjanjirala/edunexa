#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
load_env
lock
backup_data
warn 'Online media backup is not transactionally consistent with PostgreSQL. Stop writers for a coordinated snapshot; copy backups off-host.'
