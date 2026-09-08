FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Set work directory
WORKDIR /app

# Install system dependencies
# git: uv shells out to it to resolve synthlib (a private git dependency,
# synthlib plan, last of 7 modules) -- without it uv sync fails here, before
# the token below even matters.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Copy project files for dependency resolution
COPY pyproject.toml uv.lock ./

# Install Python dependencies
#
# The token arrives as a build secret, never a build ARG or a file baked
# into a layer, and is applied via the env-var GIT_CONFIG form rather than
# `git config --global`, which would write it to /root/.gitconfig inside
# this layer -- the exact leak a --mount=type=secret is supposed to
# prevent. The explicit `sh -c 'export ...; export ...; ... || uv sync'`
# form is required: an env-var-prefix before `||` only covers the first
# command in the fallback chain, so the unfrozen fallback would run
# unauthenticated.
RUN --mount=type=secret,id=gh_token sh -c ' \
    export GIT_CONFIG_COUNT=1; \
    export GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/gh_token)@github.com/.insteadOf"; \
    export GIT_CONFIG_VALUE_0="https://github.com/"; \
    uv sync --frozen || uv sync'

# Copy project
COPY . .

# Set minimal environment for collectstatic during build
ENV SECRET_KEY=build-time-key
ENV DEBUG=False

# Collect static files at build time
RUN uv run python manage.py collectstatic --noinput

# Expose port
EXPOSE 7177

# Run the application
CMD ["uv", "run", "daphne", "-b", "0.0.0.0", "-p", "7177", "synthhive.asgi:application"]
