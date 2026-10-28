#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
image="${MORI_VERIFY_IMAGE:-mori-ai:verify}"
# No host Python/Node installs: both fresh stages use the locked dependencies.
docker build --platform linux/amd64 --pull --no-cache --target verification -t "${image}-tests" .
docker run --rm --platform linux/amd64 "${image}-tests" sh -ec '
  pip check
  python -m pytest -q
  python -c "import fastapi, pydantic, sqlalchemy, asyncpg, alembic, PIL, pillow_heif, uvicorn; from importlib.metadata import version; import platform; print(platform.python_version(), platform.machine()); [print(p, version(p)) for p in [\"fastapi\",\"pydantic\",\"pydantic-settings\",\"SQLAlchemy\",\"asyncpg\",\"alembic\",\"Pillow\",\"pillow-heif\",\"uvicorn\",\"pytest\"]]"
'
docker build --platform linux/amd64 --no-cache --target runtime -t "$image" .
docker run --rm --platform linux/amd64 "$image" pip check
docker image inspect "$image" --format 'runtime image={{.Id}} platform={{.Os}}/{{.Architecture}}'
docker image inspect "${image}-tests" --format 'verification image={{.Id}}'
docker image inspect node:24-bookworm-slim python:3.12-slim-bookworm --format '{{.RepoTags}} {{json .RepoDigests}}'
