# Evidence service (ARG-061…070): one image, two processes (worker and public API).
# The whole workspace is copied: `uv sync --locked` must see every member listed in pyproject.toml.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY connectors ./connectors
COPY services ./services
RUN uv sync --locked --no-dev --package argos-evidence
# ARG-084: no extra shell in the final image (sh stays: it is the base of the system).
RUN rm -f /bin/bash /usr/bin/bash
USER 10001:10001
EXPOSE 8008
CMD ["/app/.venv/bin/python", "-m", "argos_evidence.worker"]
