FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    RELAY_PROVIDER=mock \
    RELAY_ASSET_ROOT=/app \
    RELAY_ALLOW_LIVE_GEMINI=0 \
    RELAY_STORE_PATH=/app/.state/governance.sqlite

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir ".[integrations]" \
    && useradd --uid 10001 --create-home relay \
    && mkdir -p /app/.state \
    && chown relay:relay /app/.state

# These remain beside the application for file-based fixture/static lookups.
COPY web/ ./web/
COPY scenarios/ ./scenarios/

USER relay
EXPOSE 8080

# One worker shares one local mock ledger. Cloud Run's filesystem is ephemeral;
# a durable shared budget store is a separate requirement before cloud live mode.
CMD ["sh", "-c", "exec python -m uvicorn relay_gateway.api:app --host 0.0.0.0 --port \"${PORT:-8080}\" --workers 1"]
