#!/usr/bin/env bash
# Shared functions for the host-Nginx stack only. Never source .env as shell code.
set -Eeuo pipefail
umask 077
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
ENV_FILE=${EDUNEXA_ENV_FILE:-$ROOT/.env}
STATE="$ROOT/.deploy"
log() { printf '[OK] %s\n' "$*" >&2; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
die() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }
trap 'printf "[FAIL] Stopped at line %s (exit %s). See docs/VPS_DEPLOYMENT.md recovery; services may remain stopped.\n" "$LINENO" "$?" >&2' ERR
need() { command -v "$1" >/dev/null || die "Install $1 using your approved host maintenance procedure, then retry."; }
load_env() {
    need python3
    [[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || die "Create a regular production .env: python3 scripts/env.py init .env"
    [[ $(stat -c %a "$ENV_FILE") == 600 ]] || die "Run chmod 600 '$ENV_FILE' (credentials were not changed)."
    python3 scripts/env.py validate "$ENV_FILE"
    while IFS= read -r -d '' assignment; do
        case ${assignment%%=*} in
            COMPOSE_PROJECT_NAME|POSTGRES_PASSWORD|PORT|SITE_DOMAIN|SITE_URL|ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|DEMO_MODE|WEB_CONCURRENCY|WORKER_CONCURRENCY|BACKUP_RETENTION_DAYS|UPLOAD_LIMIT)
                export "${assignment?}" ;;
        esac
    done < <(python3 scripts/env.py export "$ENV_FILE")
    export EDUNEXA_ENV_FILE="$ENV_FILE"
    export COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-edunexa}
    PORT=${PORT:-8002}
    mkdir -p "$STATE"
    chmod 700 "$STATE"
    if [[ -f "$STATE/project" && $(cat "$STATE/project") != "$COMPOSE_PROJECT_NAME" ]]; then
        die 'This checkout has deployment state for a different Compose project. Preserve the existing project identity.'
    fi
    printf '%s\n' "$COMPOSE_PROJECT_NAME" > "$STATE/project"
    if [[ -f "$STATE/image" ]]; then EDUNEXA_IMAGE=$(cat "$STATE/image"); export EDUNEXA_IMAGE; fi
}
dc() { docker compose --project-directory "$ROOT" --env-file "$ENV_FILE" -f "$ROOT/docker-compose.prod.yml" "$@"; }
lock() { need flock; exec 9>"$STATE/operation.lock"; flock -n 9 || die 'Another deployment/backup/restore is running.'; }
preflight() {
    [[ $(uname -s) == Linux ]] || die 'Run deployment scripts on Ubuntu 22.04 or newer.'
    # shellcheck disable=SC1091
    source /etc/os-release
    [[ $ID == ubuntu && ${VERSION_ID%%.*} -ge 22 ]] || die 'Supported host: Ubuntu 22.04 or newer.'
    for tool in docker nginx certbot curl openssl ss getent git; do need "$tool"; done
    docker info >/dev/null 2>&1 || die 'Docker is unavailable. Start Docker and grant this user Docker access.'
    dc version >/dev/null
    dc up --help | grep -q -- --wait-timeout || die 'Upgrade Docker Compose v2: --wait-timeout support is required.'
    dc config --quiet 2>/dev/null || die 'Invalid Compose configuration; check required .env keys. Avoid printing resolved config (secrets).'
    [[ $(df -Pk "$ROOT" | awk 'END {print $4}') -ge ${MIN_DISK_KB:-3145728} ]] || die 'Free at least 3 GiB of disk space before building.'
    local available
    available=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
    [[ $available -ge ${MIN_RAM_KB:-524288} ]] || die 'Less than 512 MiB RAM available; free memory before building.'
    [[ $available -ge 2097152 ]] || warn 'Less than 2 GiB available; monitor Video Studio and build-time memory.'
    getent ahosts "$SITE_DOMAIN" >/dev/null || die "DNS does not resolve $SITE_DOMAIN. Create the Cloudflare DNS record."
    log 'DNS resolves; proxied Cloudflare records cannot prove the origin IP. Verify the DNS dashboard manually.'
    check_port
    dc ps --status running --services
    log "Preflight passed for project $COMPOSE_PROJECT_NAME on loopback port $PORT. No host packages were changed."
}
check_port() {
    local owner
    owner=$(dc ps -q web)
    if [[ -n $(ss -H -ltn "sport = :$PORT") ]]; then
        [[ -n "$owner" ]] || die "Port $PORT is occupied by another service. Choose a free PORT and matching Nginx upstream."
        docker port "$owner" 8000/tcp | grep -Fxq "127.0.0.1:$PORT" || die 'Port is not owned by this EduNexa web container.'
    fi
}
backup_data() {
    local archive stamp
    stamp=$(date -u +%Y%m%dT%H%M%S)-$$
    archive="$STATE/backups/$stamp"
    mkdir -p "$archive"
    chmod 700 "$STATE/backups" "$archive"
    dc exec -T db pg_dump -U edunexa -d edunexa -Fc > "$archive/database.dump.partial"
    dc exec -T db pg_restore --list < "$archive/database.dump.partial" >/dev/null
    mv "$archive/database.dump.partial" "$archive/database.dump"
    # A one-off container works even when web has been stopped for an update.
    dc run --rm -T --no-deps web sh -c 'if [ -d /app/media ]; then tar -C /app/media -czf - .; else tar -czf - --files-from /dev/null; fi' > "$archive/media.tar.gz.partial"
    tar -tzf "$archive/media.tar.gz.partial" >/dev/null
    mv "$archive/media.tar.gz.partial" "$archive/media.tar.gz"
    (cd "$archive" && sha256sum database.dump media.tar.gz > SHA256SUMS)
    git rev-parse HEAD > "$archive/revision"
    log "Verified archive structure and checksums: $archive (a restore drill is still required)."
    # Retention is opt-in. Delete only complete backups in this stack's private directory.
    local days=${BACKUP_RETENTION_DAYS:-0}
    [[ $days =~ ^[0-9]+$ ]] || die 'BACKUP_RETENTION_DAYS must be a nonnegative integer.'
    if (( days > 0 )); then
        find "$STATE/backups" -mindepth 2 -maxdepth 2 -name SHA256SUMS -mtime "+$days" -print0 |
        while IFS= read -r -d '' marker; do
            local old=${marker%/SHA256SUMS}
            [[ $old != "$archive" ]] && rm -rf -- "$old"
        done
    fi
    printf '%s\n' "$archive"
}
release() {
    local revision previous existing_data=0
    revision=$(git rev-parse --short=12 HEAD)
    previous=$(dc ps -a -q web)
    if docker volume inspect "${COMPOSE_PROJECT_NAME}_postgres_data" >/dev/null 2>&1; then existing_data=1; fi
    if [[ -n "$previous" ]]; then
        docker inspect --format '{{.Image}}' "$previous" > "$STATE/previous-image"
        # Pin the previous image so a later build cannot overwrite the rollback target.
        docker image tag "$(cat "$STATE/previous-image")" "$COMPOSE_PROJECT_NAME:rollback"
    fi
    EDUNEXA_IMAGE="$COMPOSE_PROJECT_NAME:release-$revision-$(date -u +%Y%m%d%H%M%S)-$$"
    export EDUNEXA_IMAGE
    dc build web
    dc run --rm -T --no-deps web python -c 'import packaging, config.wsgi, config.celery'
    dc run --rm -T --no-deps web python manage.py check --deploy --fail-level WARNING
    if [[ -n "$previous" || $existing_data == 1 ]]; then dc stop web worker beat; fi
    dc up -d --wait --wait-timeout 180 db redis
    if [[ -n "$previous" || $existing_data == 1 ]]; then
        backup_data > "$STATE/latest-backup"
    fi
    dc run --rm -T --no-deps web python manage.py migrate --noinput
    # Static files are built into each immutable image; verify with the production settings too.
    dc run --rm -T --no-deps web python manage.py collectstatic --noinput --verbosity 0
    if [[ ${SEED_DEMO:-0} == 1 ]]; then
        [[ $DEMO_MODE == 1 ]] || die 'Demo seeding requires DEMO_MODE=1.'
        dc run --rm -T --no-deps web python manage.py initialize_demo
    fi
    dc up -d --no-deps --wait --wait-timeout 180 web worker beat
    printf '%s\n' "$EDUNEXA_IMAGE" > "$STATE/image"
    health "${LOCAL_ONLY:-0}"
    git rev-parse HEAD > "$STATE/deployed-revision"
    log "Deployment succeeded: $SITE_URL; project $COMPOSE_PROJECT_NAME; image $EDUNEXA_IMAGE"
}
http_check() {
    local code
    code=$(curl --fail --silent --show-error --max-time 30 --output /dev/null --write-out '%{http_code}' "$@") || return 1
    [[ $code == 200 ]] || { warn "HTTP check returned $code; expected 200."; return 1; }
}
health() {
    local local_only=${1:-0} failures=0 service id status
    check() { if "$@"; then log "$1 check passed"; else warn "$1 check failed"; failures=$((failures + 1)); fi; }
    for service in db redis web worker beat; do
        id=$(dc ps -q "$service")
        if [[ -z "$id" ]]; then warn "$service is not running"; failures=$((failures + 1)); continue; fi
        status=$(docker inspect --format '{{.State.Health.Status}}' "$id")
        [[ $status == healthy ]] || { warn "$service health: $status"; failures=$((failures + 1)); }
        docker inspect --format '{{.Name}}: restarts={{.RestartCount}} OOM={{.State.OOMKilled}}' "$id"
    done
    check dc exec -T db psql -U edunexa -d edunexa -v ON_ERROR_STOP=1 -c 'SELECT 1'
    check dc exec -T redis redis-cli ping
    check dc exec -T web python manage.py migrate --check
    check dc exec -T web python manage.py check --deploy --fail-level WARNING
    check dc exec -T web python manage.py check_jobs --timeout 30
    check http_check -H "Host: $SITE_DOMAIN" -H 'X-Forwarded-Proto: https' "http://127.0.0.1:$PORT/health/"
    check http_check -H "Host: $SITE_DOMAIN" -H 'X-Forwarded-Proto: https' "http://127.0.0.1:$PORT/static/css/base.css"
    if [[ $local_only != 1 ]]; then
        check http_check "https://$SITE_DOMAIN/health/"
        # Bypass Cloudflare to validate origin hostname, chain and expiry; never use curl -k.
        check http_check --resolve "$SITE_DOMAIN:443:127.0.0.1" "https://$SITE_DOMAIN/health/"
    else warn 'Public HTTPS and origin TLS checks explicitly skipped; deployment is not externally verified.'; fi
    local ids
    ids=$(dc ps -q)
    if [[ -n "$ids" ]]; then
        # IDs are Docker-produced hex tokens, not user input.
        # shellcheck disable=SC2086
        docker stats --no-stream $ids
    fi
    free -m
    df -h "$ROOT"
    (( failures == 0 )) || die "$failures critical health checks failed. Inspect scoped Compose logs; do not reset data."
}
