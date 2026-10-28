#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
project="mori-workflow-$(date +%s)-$$"
export POSTGRES_USER=mori POSTGRES_DB=mori_workflow_test POSTGRES_PASSWORD="verify_${project}"
compose() { docker compose --env-file /dev/null -p "$project" "$@"; }
cleanup() { compose down -v --remove-orphans; }
trap cleanup EXIT
compose up --no-build -d --wait --wait-timeout 120 postgres
compose exec -T postgres psql -U mori -d mori_workflow_test -Atc 'SHOW server_version;'
run() {
 docker run --rm --platform linux/amd64 --network "${project}_default" \
 -e DATABASE_URL="postgresql+asyncpg://mori:${POSTGRES_PASSWORD}@postgres:5432/mori_workflow_test" \
 -e MORI_WORKFLOW_TEST=1 -v "$PWD/backend:/app/backend:ro" \
 -v "$PWD/tests:/app/tests:ro" -v "$PWD/scripts:/app/scripts:ro" \
 "${MORI_VERIFY_TEST_IMAGE:-mori-ai:verify-tests}" "$@"
}
run python -m alembic -c backend/alembic.ini upgrade head
run python -m alembic -c backend/alembic.ini downgrade base
run python -m alembic -c backend/alembic.ini upgrade head
run python -m alembic -c backend/alembic.ini check
if [[ "$#" -eq 0 ]]; then set -- backend/tests/integration; fi
run python -m pytest "$@" -q -rs
