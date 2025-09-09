FROM python:3.10-buster AS build
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev --all-packages

FROM python:3.10-slim
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY ./app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"


CMD ["uvicorn", "main:app", "--reload"]