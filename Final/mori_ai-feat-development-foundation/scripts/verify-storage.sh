#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
test -f .env || { echo 'Create the project .env first.' >&2; exit 2; }
storage_check_project="mori-r2-check-$(date +%s)-$$"
storage_check_prefix="mori-ai-storage-check/$(python3 -c 'from uuid import uuid4; print(uuid4())')/"
export MORI_IMAGE="${MORI_STORAGE_VERIFY_IMAGE:-mori-ai:verify}"
compose_storage_check() { docker compose --env-file .env -p "$storage_check_project" "$@"; }
cleanup_storage_check() { compose_storage_check down -v --remove-orphans; }
trap cleanup_storage_check EXIT
compose_storage_check run --rm --no-deps -T \
  -e STORAGE_MODE=r2 -e R2_KEY_PREFIX="$storage_check_prefix" \
  -e PYTHONPATH=/app \
  -e DATABASE_URL=postgresql+asyncpg://mori:verify@unused/mori_storage_probe \
  -e GOOGLE_CLIENT_ID= -e GOOGLE_CLIENT_SECRET= -e GOOGLE_REDIRECT_URI= \
  -e KAKAO_CLIENT_ID= -e KAKAO_CLIENT_SECRET= -e KAKAO_REDIRECT_URI= \
  -v "$PWD/backend:/app/backend:ro" -v "$PWD/scripts:/verify:ro" \
  web python /verify/verify_storage.py
