FROM python:3.12-slim

ENV PYTHONUTF8=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip && \
    rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install uv && uv sync

RUN uv run reflex export --no-zip

RUN useradd -m appuser
USER appuser

EXPOSE 2009

# Reflex 0.9.x serves frontend + backend on a single port in prod and
# provides a built-in `/_health` endpoint that returns 200 with JSON
# liveness for db/redis (both are 'NA' here since neither is used).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-2009}/_health" || exit 1

CMD ["uv", "run", "reflex", "run", "--env", "prod"]
