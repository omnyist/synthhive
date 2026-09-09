#!/bin/bash
# Runs ON Saya, in the persistent checkout at ~/ci/deploys/synthhive.
# Caddyfile is bind-mounted; only a restart picks up changes. No live-guest
# check: this touches neither server nor bot.
set -euo pipefail

docker compose -f docker-compose.prod.yml restart caddy
docker image prune -f || true
