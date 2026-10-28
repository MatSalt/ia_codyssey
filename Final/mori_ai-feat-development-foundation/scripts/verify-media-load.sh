#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
image="${MORI_VERIFY_TEST_IMAGE:-${MORI_VERIFY_IMAGE:-mori-ai:verify}-tests}"
docker run --rm --platform linux/amd64 --memory=1g --memory-swap=1g \
  -v "$PWD:/app:ro" -w /app "$image" python -m backend.tests.media.load_probe
