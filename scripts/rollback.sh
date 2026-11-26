#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
[[ ${1:-} == --schema-compatible && $# == 1 ]] || die 'Review migrations first, then: bash scripts/rollback.sh --schema-compatible. This changes application images only.'
load_env
lock
[[ -s "$STATE/previous-image" ]] || die 'No recorded previous image. Follow manual recovery in docs/VPS_DEPLOYMENT.md.'
export EDUNEXA_IMAGE
EDUNEXA_IMAGE=$(cat "$STATE/previous-image")
docker image inspect "$EDUNEXA_IMAGE" >/dev/null
dc stop web worker beat
dc up -d --no-deps --wait --wait-timeout 180 web worker beat
printf '%s\n' "$EDUNEXA_IMAGE" > "$STATE/image"
health 0
log 'Previous application image restored. Database schema and Git checkout were not changed.'
