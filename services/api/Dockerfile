# The single API (ARG-071) with the console inside (ARG-073, ADR-0013): one image, one origin.
#
# The console is built here, from its lock file, and travels as static files next to the API: the
# appliance is air-gapped, so nothing may be fetched from a CDN at run time.
FROM node:22-slim AS console
WORKDIR /console
COPY console/package.json console/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY console ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY connectors ./connectors
COPY services ./services
RUN uv sync --locked --no-dev --package argos-api
# The challenge library and the ontology are read at runtime, never baked as data.
COPY library ./library
COPY --from=console /console/dist ./console
USER 10001
EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "argos_api.main"]
