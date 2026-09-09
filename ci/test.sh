#!/bin/sh
# Runs in a Linux task container on the worker -- the ephemeral pg/redis
# from start-services.yml are published on Saya, not localhost, since
# that's the host actually running them.
set -eu

apt-get update -qq && apt-get install -y -qq curl openssh-client git openssl jq >/dev/null

# SSH + a clone of standards.git happen once, up front, because two things
# need it before ruff/pytest can even run: gh-app-token.sh (to resolve the
# private synthlib git dependency this repo now carries) and, later,
# doctrine-grep.sh. One clone, two uses.
mkdir -p ~/.ssh
echo "$SSH_KEY" > ~/.ssh/id_ed25519
chmod 600 ~/.ssh/id_ed25519
echo "$KNOWN_HOSTS" > ~/.ssh/known_hosts

STD=$(mktemp -d)
GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519 -o UserKnownHostsFile=~/.ssh/known_hosts -o ConnectTimeout=10" \
  git clone --depth 1 -q Avalonstar@10.0.20.10:git/standards.git "$STD"

# Mint a token scoped to synthlib alone and hand it to `uv` via the env-var
# GIT_CONFIG form -- never `git config --global`, which writes to disk and
# would leak into a Docker build layer if this same pattern were copied
# there verbatim. Must happen before the first `uv run` below: that command
# implicitly runs `uv sync`, which is what actually resolves synthlib.
APP_KEY_FILE=$(mktemp)
printf '%s' "$PRIVATE_KEY" > "$APP_KEY_FILE"
GH_TOKEN=$(bash "$STD/ci/gh-app-token.sh" "$APP_ID" "$INSTALLATION_ID" "$APP_KEY_FILE" synthlib)
rm -f "$APP_KEY_FILE"
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0="url.https://x-access-token:${GH_TOKEN}@github.com/.insteadOf"
export GIT_CONFIG_VALUE_0="https://github.com/"

curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

uv run ruff check .

# Written after four production SynchronousOnlyOperation bugs from a
# cached-relation traversal inside async code -- see scripts/audit_async_fk.py.
uv run python scripts/audit_async_fk.py

export DEBUG="False"
export SECRET_KEY="test-secret-key"
export ALLOWED_HOSTS="*"
export DATABASE_URL="postgresql://synthhive:synthhive@10.0.20.10:5446/synthhive"
export REDIS_URL="redis://10.0.20.10:6405/0"

uv run --group dev pytest -q

echo "=== doctrine-grep ==="
# Full-repo content scan plus HEAD's commit message -- see
# synthcore/ci/test.sh for the fuller rationale (full scan avoids a range
# computation that check_every can silently under-cover; the commit-message
# half only checks HEAD, a real named gap, not a hidden one).
git log -1 --format=%B > /tmp/commit-msg
bash "$STD/checks/doctrine-grep.sh" "$PWD" /tmp/commit-msg
rm -rf "$STD"
