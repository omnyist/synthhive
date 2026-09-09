#!/bin/bash
# Runs ON Saya, in the persistent checkout at ~/ci/deploys/synthhive.
# frontend-build is a one-shot (restart: "no"); `up` re-runs it because it
# sits in the exited state after each build. No live-guest check: this
# touches neither server nor bot, so no chat session is affected.
set -euo pipefail

docker compose -f docker-compose.prod.yml up -d frontend-build
docker image prune -f || true
