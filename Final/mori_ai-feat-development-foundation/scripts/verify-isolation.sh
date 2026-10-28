#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Unique names prevent accidentally stopping another developer's project.
suffix="$(date +%s)-$$"
first="mori-verify-a-${suffix}"
second="mori-verify-b-${suffix}"
export POSTGRES_USER=mori POSTGRES_DB=mori
export POSTGRES_PASSWORD="verify_${suffix}"
export MORI_IMAGE="${MORI_VERIFY_IMAGE:-mori-ai:verify}"
export WEB_PORT=0 STORAGE_MODE=local STORAGE_ROOT=/app/media WORKER_POLL_SECONDS=1
compose() { docker compose --env-file /dev/null -p "$1" "${@:2}"; }
cleanup() {
  compose "$first" down -v --remove-orphans
  compose "$second" down -v --remove-orphans
}
trap cleanup EXIT
for project in "$first" "$second"; do
  compose "$project" up --no-build -d --wait --wait-timeout 120
  # A healthy HTTP shell must not hide an uninitialized worker database.
  compose "$project" exec -T postgres psql -U mori -d mori -v ON_ERROR_STOP=1 -Atc 'SELECT version_num FROM alembic_version' >/dev/null
  compose "$project" exec -T web python -c 'import urllib.request; assert urllib.request.urlopen("http://localhost:8000/health").read() == b"{\"status\":\"ok\"}"'
done
compose "$first" exec -T postgres psql -U mori -d mori -v ON_ERROR_STOP=1 -c "CREATE TABLE isolation_probe (marker text); INSERT INTO isolation_probe VALUES ('first');"
compose "$second" exec -T postgres psql -U mori -d mori -v ON_ERROR_STOP=1 -c "CREATE TABLE isolation_probe (marker text); INSERT INTO isolation_probe VALUES ('second');"
[[ "$(compose "$first" exec -T postgres psql -U mori -d mori -Atc 'SELECT marker FROM isolation_probe')" == first ]]
[[ "$(compose "$second" exec -T postgres psql -U mori -d mori -Atc 'SELECT marker FROM isolation_probe')" == second ]]
compose "$first" exec -T web sh -c 'echo first > /app/media/isolation_probe'
compose "$second" exec -T web sh -c 'echo second > /app/media/isolation_probe'
[[ "$(compose "$first" exec -T worker cat /app/media/isolation_probe)" == first ]]
[[ "$(compose "$second" exec -T worker cat /app/media/isolation_probe)" == second ]]
for project in "$first" "$second"; do
  compose "$project" exec -T web python - <<'PY'
import urllib.request
import urllib.error
for path in ["/", "/albums", "/albums/example/edit"]:
    with urllib.request.urlopen("http://localhost:8000" + path) as r:
        assert r.status == 200 and "text/html" in r.headers["Content-Type"]
for path in ["/api/v1/absent", "/assets/absent.js", "/favicon.ico"]:
    try:
        urllib.request.urlopen("http://localhost:8000" + path)
    except urllib.error.HTTPError as e:
        assert e.code == 404 and "text/html" not in e.headers["Content-Type"]
    else:
        raise AssertionError(path + " did not return 404")
PY
  worker_id="$(compose "$project" ps -q worker)"
  compose "$project" stop -t 10 worker
  [[ "$(docker inspect "$worker_id" --format '{{.State.ExitCode}}')" == 0 ]]
  compose "$project" logs worker
  compose "$project" ps
  docker inspect "$(compose "$project" ps -q postgres)" --format '{{range .Mounts}}{{.Name}} {{end}}'
  docker inspect "$(compose "$project" ps -q web)" --format '{{range .Mounts}}{{.Name}} {{end}}'
done
printf 'PASS: two PostgreSQL databases and media volumes are isolated; each web/worker pair shares media; worker SIGTERM exits 0.\n'
