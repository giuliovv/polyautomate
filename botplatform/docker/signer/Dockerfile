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
COPY signer/ signer/
COPY backend/ backend/
COPY executor/ executor/

# Expose port
EXPOSE 8001

# Default command
CMD ["uvicorn", "signer.main:app", "--host", "0.0.0.0", "--port", "8001"]
