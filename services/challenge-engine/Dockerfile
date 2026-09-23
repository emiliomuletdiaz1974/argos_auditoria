# Campaign engine (ARG-041…050): one image, two entry points (worker and API).
# The whole workspace is copied: `uv sync --locked` must see every member listed in pyproject.toml.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY connectors ./connectors
COPY services ./services
RUN uv sync --locked --no-dev --package argos-challenge-engine
# The challenge library and the ontology are read at runtime, never baked as data.
COPY library ./library
# ARG-084: no extra shell in the final image (sh stays: it is the base of the system).
RUN rm -f /bin/bash /usr/bin/bash
USER 10001:10001
EXPOSE 8003
CMD ["/app/.venv/bin/python", "-m", "argos_challenges.worker"]
