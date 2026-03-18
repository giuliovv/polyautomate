FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install polyautomate package first (from root)
COPY pyproject.toml README.md /app/polyautomate/
COPY polyautomate/ /app/polyautomate/polyautomate/

# Install polyautomate with backtest dependencies
WORKDIR /app/polyautomate
RUN pip install --no-cache-dir ".[backtest]"

# Switch back to main app directory
WORKDIR /app

# Copy botplatform project files
COPY botplatform/pyproject.toml botplatform/README.md ./

# Install botplatform dependencies
RUN pip install --no-cache-dir .

# Copy application code
COPY botplatform/backend/ backend/
COPY botplatform/signer/ signer/
COPY botplatform/executor/ executor/

# Expose port
EXPOSE 8000

# Default command
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
