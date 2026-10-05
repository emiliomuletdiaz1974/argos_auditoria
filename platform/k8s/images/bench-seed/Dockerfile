# K-07 · what prepares and seeds the simulated sources of the bench: the same tools and SQL as the
# development environment, with the dependencies of uv.lock (argos-inventory carries the clients of
# every source). It is not a service of ARGOS and never runs outside bench-sources.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY connectors ./connectors
COPY services ./services
RUN uv sync --locked --no-dev --package argos-inventory
COPY tools/prepare_dev_sources.py tools/seed_dev_clinical.py ./tools/
COPY deploy/dev/sources/postgres ./sources/postgres
COPY deploy/dev/sources/mariadb ./sources/mariadb
RUN rm -f /bin/bash /usr/bin/bash
USER 10001:10001
