# Public verifier (ARG-069). No database, no store, no secret: it checks what it is sent.
# The whole workspace is copied: `uv sync --locked` must see every member listed in pyproject.toml.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY connectors ./connectors
COPY services ./services
RUN uv sync --locked --no-dev --package argos-verifier
USER 10001
EXPOSE 8007
CMD ["/app/.venv/bin/python", "-m", "argos_verifier.main"]
