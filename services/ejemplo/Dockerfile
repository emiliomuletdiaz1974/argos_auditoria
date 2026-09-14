# Servicio de ejemplo de la Fase 1.
# Al añadir miembros al workspace, copiar también sus pyproject.toml para que `uv sync --locked` resuelva.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY services/ejemplo ./services/ejemplo
RUN uv sync --locked --no-dev --package argos-ejemplo
USER 10001
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "argos_ejemplo.app:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "10"]
