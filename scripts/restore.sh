#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
[[ $# == 2 && $2 == --replace-database ]] || die 'Usage: bash scripts/restore.sh /absolute/backup-directory --replace-database'
archive=$(realpath "$1")
load_env
lock
(cd "$archive" && sha256sum --check SHA256SUMS)
dc exec -T db pg_restore --list < "$archive/database.dump" >/dev/null
stamp=$(date -u +%Y%m%d%H%M%S)_$$
restored="edunexa_restore_$stamp"
replaced="edunexa_replaced_$stamp"
sql() { dc exec -T db psql -U edunexa -d postgres -v ON_ERROR_STOP=1 -c "$1"; }
sql "CREATE DATABASE $restored"
dc exec -T db pg_restore -U edunexa -d "$restored" --no-owner --exit-on-error < "$archive/database.dump"
dc stop web worker beat
backup_data > "$STATE/pre-restore-backup"
# Renames are transactional; reject connections while swapping to close reconnect races.
sql "ALTER DATABASE edunexa WITH ALLOW_CONNECTIONS false"
sql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'edunexa'"
if ! sql "BEGIN; ALTER DATABASE edunexa RENAME TO $replaced; ALTER DATABASE $restored RENAME TO edunexa; COMMIT;"; then
    sql "ALTER DATABASE edunexa WITH ALLOW_CONNECTIONS true"
    die 'Swap failed. Original database retained; services remain stopped for inspection.'
fi
log "Database restored. Previous database retained as $replaced. Services remain stopped."
warn "Media is NOT overwritten. Review $archive/media.tar.gz, schema compatibility and queued Redis tasks before restarting. See restore runbook."
