#!/bin/bash
# Runs ON Saya, in the persistent checkout at ~/ci/deploys/synthhive.
# Expects OWNER in the environment. server and bot share one Dockerfile, so
# `compose build` rebuilds both regardless -- matches the original GHA job's
# "Rebuild images" step, which rebuilt everything before restarting server+bot.
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
    echo "::error:: Live guest channel(s):$live -- restarting server/bot would interrupt their stream. Wait until they are offline."
    exit 1
  fi
fi

docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d server bot
docker image prune -f || true
