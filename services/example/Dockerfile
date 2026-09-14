# Phase 1 example service.
# When adding workspace members, copy their pyproject.toml too so `uv sync --locked` can resolve.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY services/example ./services/example
RUN uv sync --locked --no-dev --package argos-example
USER 10001
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "argos_example.app:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "10"]
