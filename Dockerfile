FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip && \
    rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install uv && uv sync

RUN uv run reflex export --no-zip

EXPOSE 2009 8000

CMD ["uv", "run", "reflex", "run", "--env", "prod"]
