#!/usr/bin/env bash
# Server-only: sudo bash scripts/lightsail-deploy.sh <full Git commit SHA>
set -Eeuo pipefail
cd "$(dirname "$0")/.."
umask 077
revision=${1:-}
if [[ $# != 1 || ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Usage: sudo bash scripts/lightsail-deploy.sh <40-character commit SHA from successful Actions run>' >&2
  exit 2
fi
for tool in docker git python3 flock curl; do command -v "$tool" >/dev/null; done
[[ -f .env.production ]] || { echo 'Missing .env.production' >&2; exit 1; }
mkdir -p .local
exec 9>.local/lightsail-deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
# sudo may run against the ubuntu-owned repository; trust only this explicit path per command.
git_cmd() { git -c "safe.directory=$PWD" "$@"; }
# Preserve the server's ZeroSSL Caddyfile. All other tracked edits must be resolved first.
if [[ -n "$(git_cmd status --porcelain --untracked-files=no -- . ':!deploy/lightsail/Caddyfile')" ]]; then
  echo 'Tracked server edits found outside Caddyfile. Reconcile them before deploying.' >&2
  exit 1
fi
git_cmd fetch origin "$revision"
[[ "$(git_cmd rev-parse FETCH_HEAD)" == "$revision" ]]
# Never overwrite a divergent checkout or local Caddy changes.
git_cmd merge --ff-only "$revision"
image="ghcr.io/jimchoi9/mori_ai:sha-$revision"
docker pull "$image"
actual=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
[[ "$actual" == "$revision" ]] || { echo 'Image revision mismatch.' >&2; exit 1; }
# Pin deployment to the downloaded immutable digest, not a mutable tag.
digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$image")
[[ "$digest" =~ ^ghcr.io/jimchoi9/mori_ai@sha256:[0-9a-f]{64}$ ]] || exit 1
export MORI_IMAGE="$digest"
compose() { bash scripts/lightsail.sh "$@"; }
compose config --quiet
# Check image configuration without starting app, writing data or making external API calls.
compose run --rm --no-deps --pull never web python -c 'from backend.settings import Settings; Settings(); print("Runtime settings valid")'
bash scripts/lightsail-backup.sh
cp .env.production ".local/env-before-${revision}-$(date -u +%Y%m%dT%H%M%SZ)-$$"
phase=stopping
trap 'echo "Deployment interrupted during $phase. Inspect services; no automatic DB rollback was attempted." >&2' ERR
compose stop web worker
phase=migration
compose run --rm --no-deps --pull never migrate
phase=starting
compose up -d --no-build --pull never --wait --wait-timeout 120 web worker
phase=https-check
curl --fail --silent --show-error --max-time 15 https://aimori.kro.kr/health
# Persist only the image selection after successful startup. Keep secrets and policy values intact.
phase=persisting
python3 - "$digest" <<'PY'
import os, re, sys
from pathlib import Path
p=Path('.env.production')
s=p.read_text()
s=re.sub(r'^MORI_IMAGE=.*(?:\n|$)', '', s, flags=re.M)
tmp=p.with_name('.env.production.next')
try:
    with tmp.open('x') as f:
        os.chmod(tmp, 0o600)
        owner=p.stat()
        if os.geteuid() == 0:
            os.chown(tmp, owner.st_uid, owner.st_gid)
        f.write(s.rstrip()+'\nMORI_IMAGE='+sys.argv[1]+'\n')
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(p)
finally:
    if tmp.exists():
        tmp.unlink()
PY
trap - ERR
printf '\nDeployment complete: %s\n' "$revision"
compose ps
