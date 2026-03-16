# Bot Platform

A self-hosted Polymarket bot platform that allows users to create trading bots without sharing their private keys.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   Backend   │────▶│   Signer    │
│  (Next.js)  │     │  (FastAPI)  │     │  (FastAPI)  │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                   │
                           ▼                   ▼
                    ┌─────────────┐     ┌─────────────┐
                    │  PostgreSQL │◀────│   Executor  │
                    └─────────────┘     └─────────────┘
```

- **Frontend**: Next.js dashboard for managing wallets, bots, and viewing trades
- **Backend**: FastAPI REST API for user auth, wallet/bot CRUD, trade history
- **Signer**: Isolated service that holds encrypted private keys and signs orders
- **Executor**: Runs trading strategies and communicates with the signer

## Key Features

- **Platform-managed wallets**: We generate and encrypt wallet keys
- **Delegated wallets**: Users can connect existing wallets
- **Secure signing**: Private keys never leave the signer service
- **Audit logging**: All signing operations are logged
- **Risk management**: Per-bot position limits and loss limits

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Node.js 20+ (for frontend development)
- Python 3.10+ (for backend development)

### Development with Docker Compose

```bash
cd botplatform/docker
docker-compose up -d
```

This starts:
- PostgreSQL on port 5432
- Redis on port 6379
- Backend API on http://localhost:8000
- Signer service on http://localhost:8001
- Frontend on http://localhost:3000

### Manual Development

1. **Install Python dependencies**:
   ```bash
   cd botplatform
   pip install -e ".[dev]"
   ```

2. **Start PostgreSQL and Redis** (or use Docker):
   ```bash
   docker-compose up -d postgres redis
   ```

3. **Run the backend**:
   ```bash
   uvicorn backend.main:app --reload
   ```

4. **Run the signer** (in a separate terminal):
   ```bash
   uvicorn signer.main:app --port 8001 --reload
   ```

5. **Run the executor** (in a separate terminal):
   ```bash
   python -m executor.runner
   ```

6. **Run the frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

## Configuration

### Environment Variables

#### Backend
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `JWT_SECRET_KEY`: Secret for JWT signing
- `SIGNER_URL`: URL of the signer service
- `SIGNER_SHARED_SECRET`: Shared secret for signer authentication

#### Signer
- `SIGNER_DATABASE_URL`: PostgreSQL connection string
- `SIGNER_BACKEND_SHARED_SECRET`: Shared secret for backend authentication
- `SIGNER_KMS_KEY_ID`: AWS KMS key ID for envelope encryption (optional)

#### Executor
- `EXECUTOR_DATABASE_URL`: PostgreSQL connection string
- `EXECUTOR_SIGNER_URL`: URL of the signer service
- `EXECUTOR_DRY_RUN`: Set to "true" to disable actual trading

## API Endpoints

### Authentication
- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/login` - Login
- `POST /api/v1/auth/refresh` - Refresh access token

### Wallets
- `POST /api/v1/wallets` - Create platform-managed wallet
- `POST /api/v1/wallets/delegate` - Link existing wallet
- `GET /api/v1/wallets` - List wallets
- `GET /api/v1/wallets/{id}` - Get wallet details

### Bots
- `POST /api/v1/bots` - Create bot
- `GET /api/v1/bots` - List bots
- `PATCH /api/v1/bots/{id}` - Update bot config
- `POST /api/v1/bots/{id}/start` - Start bot
- `POST /api/v1/bots/{id}/stop` - Stop bot

### Trades
- `GET /api/v1/trades` - List all trades
- `GET /api/v1/trades/summary` - Get P&L summary

## Security

- Private keys are encrypted using AES-256-GCM
- In production, keys are wrapped with AWS KMS (envelope encryption)
- The signer service runs in an isolated network with no public access
- All signing requests are authenticated with HMAC
- Comprehensive audit logging for all signing operations

## Strategies

Currently available strategies:
- **Longshot**: Buys NO on low-probability YES outcomes (Kelly-optimal sizing)

## License

Proprietary - All rights reserved
