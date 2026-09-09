#!/bin/bash
# Runs ON Saya, right after any deploy-*.sh. Mandatory read-back per
# deploy.md -- the shared compose-inspect block, same shape as every other
# module's ci/verify.sh.
set -uo pipefail

sleep 30

ids=$(docker compose -f docker-compose.prod.yml ps -aq)
if [ -z "$ids" ]; then
  echo "No containers found for this compose project."
  exit 1
fi

failed=""
for cid in $ids; do
  info=$(docker inspect --format '{{.Name}} {{.State.Status}} {{.State.ExitCode}}' "$cid")
  name=$(echo "$info" | cut -d' ' -f1 | sed 's|^/||')
  state=$(echo "$info" | cut -d' ' -f2)
  code=$(echo "$info" | cut -d' ' -f3)
  case "$state" in
    running|created)
      echo "ok: $name ($state)"
      ;;
    exited)
      # frontend-build is a one-shot; exit 0 is success, not a failure.
      if [ "$code" = "0" ]; then
        echo "ok: $name (exited 0, one-shot)"
      else
        echo "FAILED: $name exited $code"
        failed="$failed $name"
      fi
      ;;
    *)
      echo "FAILED: $name is $state"
      failed="$failed $name"
      ;;
  esac
done

if [ -n "$failed" ]; then
  for name in $failed; do
    echo "----- $name: last 30 log lines -----"
    docker logs --tail 30 "$name" 2>&1 || true
  done
  echo "Deploy verification failed:$failed"
  exit 1
fi
