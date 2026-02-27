#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
docker run -d \
  --name docker-web-1 \
  --network docker_default \
  --env-file "${SCRIPT_DIR}/web-custom.env" \
  -e ENABLE_WEBSITE_FIRECRAWL=true \
  -e TEXT_GENERATION_TIMEOUT_MS=60000 \
  -e MAX_ITERATIONS_NUM=99 \
  -e TOP_K_MAX_VALUE=10 \
  -e NEXT_TELEMETRY_DISABLED=0 \
  -e ALLOW_UNSAFE_DATA_SCHEME=false \
  -e MAX_TOOLS_NUM=10 \
  -e CONSOLE_API_URL="" \
  -e MAX_TREE_DEPTH=50 \
  -e NEXT_PUBLIC_COOKIE_DOMAIN="" \
  -e SENTRY_DSN="" \
  -e LOOP_NODE_MAX_COUNT=100 \
  -e AMPLITUDE_API_KEY="" \
  -e INDEXING_MAX_SEGMENTATION_TOKENS_LENGTH=4000 \
  -e ENABLE_WEBSITE_JINAREADER=true \
  -e MAX_PARALLEL_LIMIT=10 \
  -e ENABLE_WEBSITE_WATERCRAWL=true \
  -e MARKETPLACE_URL=https://marketplace.dify.ai \
  -e APP_API_URL="" \
  -e CSP_WHITELIST="" \
  -e PM2_INSTANCES=2 \
  -e ALLOW_EMBED=false \
  -e MARKETPLACE_API_URL=https://marketplace.dify.ai \
  -e NEXT_PUBLIC_BASE_PATH="" \
  -e NODE_ENV=production \
  -e EDITION=SELF_HOSTED \
  -e DEPLOY_ENV=PRODUCTION \
  -e PORT=3000 \
  -e TZ=UTC \
  dify-web-custom:1.13.0
