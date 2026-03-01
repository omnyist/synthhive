FROM python:3.13-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Copy project files for dependency resolution
COPY pyproject.toml uv.lock ./

# Install Python dependencies
RUN uv sync --frozen

# Copy project
COPY . .

# Set minimal environment for collectstatic during build
ENV SECRET_KEY=build-time-key
ENV DEBUG=False

# Collect static files at build time
RUN uv run python manage.py collectstatic --noinput

# Expose port
EXPOSE 7175

# Run the application
CMD ["uv", "run", "daphne", "-b", "0.0.0.0", "-p", "7175", "botbesties.asgi:application"]
