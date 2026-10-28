# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN node --version && npm --version && npm ci && npm ls --depth=0
COPY frontend/ ./
RUN npm run build
RUN ./node_modules/.bin/tsc src/api/client.ts --target ES2022 --module ES2022 --moduleResolution Bundler --lib ES2022,DOM --skipLibCheck --rootDir src --outDir /tmp/client-check \
    && node tests/upload_headers.test.mjs file:///tmp/client-check/api/client.js \
    && node tests/generation_client.test.mjs file:///tmp/client-check/api/client.js
RUN ./node_modules/.bin/tsc src/features/uploads/selection.ts src/features/generation/flow.ts src/features/review/leaveGuard.ts src/features/albums/removeAlbum.ts --target ES2022 --module ES2022 --moduleResolution Bundler --lib ES2022,DOM --skipLibCheck --rootDir src --outDir /tmp/upload-check \
    && node tests/upload_selection.test.mjs file:///tmp/upload-check/features/uploads/selection.js \
    && node tests/generation_flow.test.mjs file:///tmp/upload-check/features/generation/flow.js \
    && node tests/generation_leave.test.mjs file:///tmp/upload-check/features/review/leaveGuard.js \
    && node tests/generation_delete.test.mjs file:///tmp/upload-check/features/albums/removeAlbum.js
RUN ./node_modules/.bin/esbuild tests/generation_session_entry.ts --bundle --platform=node --format=esm --external:@tanstack/react-query --outfile=/tmp/session-check.mjs \
    && node tests/session_reset.test.mjs file:///tmp/session-check.mjs \
    && node tests/generation_session.test.mjs file:///tmp/session-check.mjs \
    && node tests/generation_recovery.test.mjs file:///tmp/session-check.mjs
RUN ./node_modules/.bin/tsc src/features/auth/oauth.ts --target ES2022 --module ES2022 --moduleResolution Bundler --lib ES2022,DOM --skipLibCheck --rootDir src --outDir /tmp/oauth-check \
    && ./node_modules/.bin/esbuild src/features/auth/AuthGate.tsx --bundle --platform=node --format=esm --packages=external --jsx=automatic --outfile=/build/auth-gate-check.mjs \
    && node tests/oauth_login.test.mjs file:///tmp/oauth-check/features/auth/oauth.js file:///build/auth-gate-check.mjs
RUN ./node_modules/.bin/tsc src/features/uploads/putFile.ts --target ES2022 --module ES2022 --moduleResolution Bundler --lib ES2022,DOM --skipLibCheck --rootDir src --outDir /tmp/r2-upload-check \
    && node tests/r2_upload.test.mjs file:///tmp/r2-upload-check/features/uploads/putFile.js

RUN node tests/ui_components.test.mjs && node tests/review_navigation.test.mjs && node tests/generation_steps.test.mjs

RUN node tests/upload_preprocess.test.mjs ../src/features/uploads/preprocess.ts \
    && node tests/upload_preprocess_hook.test.mjs

RUN ./node_modules/.bin/tsc src/features/viewer/musicPlayback.ts --target ES2022 --module ES2022 --moduleResolution Bundler --lib ES2022,DOM --skipLibCheck --outDir /tmp/music-check \
    && node tests/music_playback.test.mjs file:///tmp/music-check/musicPlayback.js

RUN node tests/goods_workflow.test.mjs && node tests/goods_geometry.test.mjs \
    && node tests/goods_mockup.test.mjs \
    && node tests/goods_catalog.test.mjs \
    && node tests/goods_components.test.mjs \
    && ./node_modules/.bin/esbuild src/features/goods/mockup/renderer.ts --bundle --platform=node --format=esm --outfile=/tmp/goods-renderer.mjs \
    && node tests/goods_renderer.test.mjs file:///tmp/goods-renderer.mjs

FROM python:3.12-slim-bookworm AS backend-base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock && pip check

FROM backend-base AS verification
COPY backend/requirements-dev.lock /tmp/requirements-dev.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements-dev.lock && pip check
COPY backend/ /app/backend/
COPY assets/audio/bgm.mp3 /app/assets/audio/bgm.mp3
COPY scripts/ /app/scripts/
COPY tests/fixtures/media/ /app/tests/fixtures/media/
COPY --from=frontend /build/dist /app/frontend/dist
RUN python -m pytest -q

FROM backend-base AS runtime
RUN groupadd --gid 10001 mori && useradd --uid 10001 --gid mori --no-create-home mori \
    && mkdir -p /app/media && chown mori:mori /app/media
COPY --chown=mori:mori backend/ /app/backend/
COPY --chown=mori:mori assets/audio/bgm.mp3 /app/assets/audio/bgm.mp3
COPY --from=frontend --chown=mori:mori /build/dist /app/frontend/dist
USER mori
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
