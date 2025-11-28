FROM python:3.10 AS build
WORKDIR /app
# Bring in uv for dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml .
COPY uv.lock .
# Ensure uv creates the venv in /app/.venv during the build stage too
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN uv sync --frozen --no-dev

FROM python:3.10-slim
WORKDIR /app

# Copy uv from the build stage
COPY --from=build /bin/uv /bin/uv

# Configure venv path before syncing so binaries go into /app/.venv
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

# Copy project files required for dependency install
COPY pyproject.toml .
COPY uv.lock .

# Install dependencies in production stage into /app/.venv
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

EXPOSE 8000

# Use PATH-resolved gunicorn from /app/.venv/bin
CMD ["gunicorn", "app.main:app", "--workers", "1", "--bind", "0.0.0.0:8000", "-k", "uvicorn.workers.UvicornWorker"]
