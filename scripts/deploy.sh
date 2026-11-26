#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
for arg in "$@"; do
    case "$arg" in
        --seed-demo) export SEED_DEMO=1 ;;
        --local-only) export LOCAL_ONLY=1 ;;
        *) die 'Usage: bash scripts/deploy.sh [--seed-demo] [--local-only]' ;;
    esac
done
if [[ ! -e "$ENV_FILE" ]]; then
    need python3
    python3 scripts/env.py init "$ENV_FILE"
    die 'Fresh .env created. Configure SMTP (or DEMO_MODE=1 for a disposable demo), then run this command again.'
fi
load_env
lock
preflight
release
