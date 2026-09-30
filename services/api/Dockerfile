# The single API (ARG-071). It serves no page: the front end is its own application (ARG-073).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY connectors ./connectors
COPY services ./services
# F10-08: the limits of each size of the appliance.
COPY platform/operation ./platform/operation
RUN uv sync --locked --no-dev --package argos-api
# The challenge library and the ontology are read at runtime, never baked as data.
COPY library ./library
# F10-07: the book of operation, which the operation screen shows next to each alert.
COPY docs/operacion ./docs/operacion
# ARG-084: no extra shell in the final image (sh stays: it is the base of the system).
RUN rm -f /bin/bash /usr/bin/bash
USER 10001:10001
EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "argos_api.main"]
