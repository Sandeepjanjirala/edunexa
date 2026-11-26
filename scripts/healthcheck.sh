#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
[[ $# == 0 || ( $# == 1 && $1 == --local-only ) ]] || die 'Usage: bash scripts/healthcheck.sh [--local-only]'
load_env
health "$([[ ${1:-} == --local-only ]] && echo 1 || echo 0)"
