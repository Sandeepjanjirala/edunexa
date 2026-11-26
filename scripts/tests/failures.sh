#!/usr/bin/env bash
# Deterministic orchestration fault tests. Docker operations below are MOCKS.
set -Eeuo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
STATE="$work/state"
mkdir -p "$STATE"
export SITE_URL=https://test.example.com
export COMPOSE_PROJECT_NAME=edunexa-test
export DEMO_MODE=0
export CALLS="$work/calls"
git() { echo testrevision; }
docker() { echo "docker $*" >> "$CALLS"; }
health() { echo health >> "$CALLS"; }
backup_data() { echo backup >> "$CALLS"; }
dc() {
    echo "$*" >> "$CALLS"
    if [[ $* == 'ps -a -q web' ]]; then echo old-container; fi
    if [[ ${FAIL_AT:-} == database && $* == 'up -d --wait --wait-timeout 180 db redis' ]]; then return 9; fi
    if [[ ${FAIL_AT:-} == migration && $* == *'manage.py migrate --noinput'* ]]; then return 8; fi
}
for fault in database migration; do
    : > "$CALLS"
    # A fresh shell/subshell with errexit active is necessary; testing `if release` would disable it.
    set +e
    (set -e; FAIL_AT=$fault; release)
    status=$?
    set -e
    [[ $status != 0 ]]
    if grep -q '^up -d --no-deps.*web worker beat' "$CALLS"; then exit 1; fi
    [[ ! -e "$STATE/image" ]]
done
: > "$CALLS"
release
release
[[ $(grep -c '^health$' "$CALLS") == 2 ]]
[[ $(grep -c 'manage.py migrate --noinput' "$CALLS") == 2 ]]
[[ $(grep -c '^backup$' "$CALLS") == 2 ]]
echo 'PASS: mocked DB/migration failure stops before application restart; repeated releases each back up and migrate once.'
PORT=8002
ss() { echo occupied; }
dc() { :; }
set +e
(check_port)
status=$?
set -e
[[ $status != 0 ]]
dc() { echo existing-web; }
docker() { echo 127.0.0.1:8002; }
check_port
echo 'PASS: mocked occupied foreign port refused; existing EduNexa loopback binding accepted.'
curl() { echo 301; }
if http_check https://test.example.com/health/; then exit 1; fi
curl() { echo 200; }
http_check https://test.example.com/health/
echo 'PASS: mocked HTTP redirects are not accepted as healthy responses.'
