FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY botplatform/frontend/package.json botplatform/frontend/package-lock.json* ./
RUN npm install

# Copy application code
COPY botplatform/frontend/ .

# Expose port
EXPOSE 3000

# Default command
CMD ["npm", "run", "dev"]
