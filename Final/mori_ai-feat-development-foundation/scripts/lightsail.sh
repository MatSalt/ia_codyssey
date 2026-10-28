#!/usr/bin/env bash
# Invoke with bash; runs only the dedicated production Compose project.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env.production ]]; then
  echo 'Create .env.production from deploy/lightsail/production.env.example first.' >&2
  exit 1
fi
exec docker compose --env-file .env.production -p mori-lightsail-prod -f compose.lightsail.yaml "$@"
