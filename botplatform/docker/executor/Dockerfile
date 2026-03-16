FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./

# Install Python dependencies
RUN pip install --no-cache-dir .

# Copy application code
COPY executor/ executor/
COPY backend/ backend/
COPY signer/ signer/

# Default command
CMD ["python", "-m", "executor.runner"]
