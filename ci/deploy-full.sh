#!/bin/bash
# Runs ON Saya, in the persistent checkout at ~/ci/deploys/synthhive.
# Expects OWNER in the environment (the tenant slug whose own stream is safe
# to restart through -- everyone else is a guest, protected by default).
set -euo pipefail

keys=$(docker exec synthcore-redis redis-cli -n 0 --scan --pattern 'stream:*:live' 2>/dev/null || true)
if [ -z "$keys" ]; then
  echo "::warning:: Could not read live flags from Redis -- proceeding without the guest check."
else
  live=""
  for key in $keys; do
    slug="${key#stream:}"
    slug="${slug%:live}"
    if [ "$slug" = "$OWNER" ]; then
      continue
    fi
    state=$(docker exec synthcore-redis redis-cli -n 0 get "$key" 2>/dev/null | tr -d '\r')
    if [ "$state" = "true" ]; then
      live="$live $slug"
    fi
  done
  if [ -n "$live" ]; then
    echo "::error:: Live guest channel(s):$live -- a full deploy restarts server and bot, dropping their chat mid-stream. Wait until they are offline."
    exit 1
  fi
fi

docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
docker compose -f docker-compose.prod.yml restart caddy
# Cleanup, not verification -- see ci/verify.sh, which runs after this and
# is what actually decides whether the deploy passed.
docker image prune -f || true
