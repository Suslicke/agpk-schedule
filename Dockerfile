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

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Configure venv path
ENV VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH

# Copy ONLY the venv from build stage (dependencies already installed)
COPY --from=build /app/.venv /app/.venv

# Copy application code
COPY . .

EXPOSE 8000

# Use PATH-resolved gunicorn from /app/.venv/bin
# --preload: Load application code before forking workers (catch import errors early)
# --timeout 120: Prevent worker timeout during long operations
# --graceful-timeout 30: Allow graceful shutdown
# --max-requests 1000: Recycle workers to prevent memory leaks
# --log-level info: Show startup errors
CMD ["gunicorn", "app.main:app", \
     "--workers", "1", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--preload", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--log-level", "info"]
