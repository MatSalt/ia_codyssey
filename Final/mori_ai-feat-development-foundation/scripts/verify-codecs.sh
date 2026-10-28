#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
image="${MORI_VERIFY_TEST_IMAGE:-${MORI_VERIFY_IMAGE:-mori-ai:verify}-tests}"
docker run --rm --platform linux/amd64 --memory=1g --memory-swap=1g \
  -v "$PWD:/app:ro" -w /app "$image" sh -ec '
python -c "import platform,PIL,pillow_heif; from PIL import features; print(platform.platform(),platform.machine(),PIL.__version__,pillow_heif.__version__,pillow_heif.libheif_info()); assert features.check(\"webp\") and features.check(\"littlecms2\")"
python -m pytest backend/tests/media -q -p no:cacheprovider
'
