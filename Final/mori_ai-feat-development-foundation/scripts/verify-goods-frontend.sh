#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Existing build image supplies locked dependencies. No QA process or data mounts.
image="${MORI_GOODS_FRONTEND_IMAGE:-mori-goods:baseline}"
docker run --rm --network none -v "$PWD/frontend:/input:ro" "$image" sh -ec '
  mkdir /tmp/goods-check
  cp -R /input/. /tmp/goods-check/
  ln -s /build/node_modules /tmp/goods-check/node_modules
  cd /tmp/goods-check
  npm run build
  node tests/goods_geometry.test.mjs
  node tests/goods_mockup.test.mjs
  node tests/goods_catalog.test.mjs
  node tests/goods_components.test.mjs
  ./node_modules/.bin/esbuild src/features/goods/mockup/renderer.ts --bundle --platform=node --format=esm --outfile=/tmp/goods-renderer.mjs
  node tests/goods_renderer.test.mjs file:///tmp/goods-renderer.mjs
'
