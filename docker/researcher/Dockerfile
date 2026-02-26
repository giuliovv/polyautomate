FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ca-certificates \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (optional at runtime if API key is provided).
RUN npm install -g @anthropic-ai/claude-code || true

COPY pyproject.toml README.md ./
COPY polyautomate ./polyautomate
COPY examples ./examples

RUN pip install --no-cache-dir .[backtest,deploy]

COPY docker/researcher/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
