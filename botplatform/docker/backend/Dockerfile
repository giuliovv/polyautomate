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
COPY backend/ backend/
COPY signer/ signer/
COPY executor/ executor/

# Expose port
EXPOSE 8000

# Default command
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
