# AI gateway (ARG-051…060). The weights of the model never go into the image: the model is served
# by its own container (the `llm` service) and is configuration, not code (ADR-0009).
# The whole workspace is copied: `uv sync --locked` must see every member listed in pyproject.toml.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY connectors ./connectors
COPY services ./services
RUN uv sync --locked --no-dev --package argos-ai-gateway
# Prompts, guardrail patterns and the challenge library are read at runtime: content, not code.
COPY library ./library
# ARG-084: no extra shell in the final image (sh stays: it is the base of the system).
RUN rm -f /bin/bash /usr/bin/bash
USER 10001:10001
EXPOSE 8005
CMD ["/app/.venv/bin/python", "-m", "argos_ai.api.main"]
