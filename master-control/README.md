# Master Control (Backend + Frontend)

This folder contains the master control panel for managing connected agents:
- `master-backend`: FastAPI app handling agents, admin auth, and dashboard WebSocket
- `master-frontend`: React/Vite dashboard UI with admin login

## Environment Setup

### Backend (`master-backend/.env`)
Copy `.env.example` to `.env` in `master-backend`, then edit values:

```
# Frontend origins allowed by CORS (comma-separated)
MASTER_FRONTEND_URL=http://localhost:5174
MASTER_FRONTEND_URLS=http://localhost:5174,http://localhost:5173

# Backend config
MASTER_BACKEND_PORT=9000
AGENTS_REGISTRY_PATH=config/agents.json

# Admin auth (change in production)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
ADMIN_SECRET=dev-secret
ADMIN_TOKEN_TTL=7200
```

Notes:
- `ADMIN_SECRET` signs HMAC tokens. Use a strong secret in production.
- `MASTER_FRONTEND_URLS` allows multiple dev ports; override for production.

### Frontend (`master-frontend`)
Copy `.env.example` to `.env` in `master-frontend` if your backend runs on a non-default host/port:

```
VITE_MASTER_API_URL=http://localhost:9000
VITE_DASHBOARD_WS_URL=ws://localhost:9000/ws/dashboard
```

## Agent connection URL (hardcoded)

Agents now use a hardcoded WebSocket URL for connecting to Master Control.
To change it:

1. Open `backend/main.py` in the agent project.
2. Find the line:

```python
MASTER_CONTROL_WS_URL = 'ws://localhost:9000/ws/agent'
```

3. Replace the string with your Master Control URL, for example:

```python
MASTER_CONTROL_WS_URL = 'wss://my-master.example.com/ws/agent'
```

4. Restart the agent backend.

Note: The agent no longer reads `MASTER_CONTROL_WS_URL` from `.env`.

## Development

### Start Backend
```
cd master-control/master-backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 9000
```

### Start Frontend
```
cd master-control/master-frontend
npm install
npm run dev
# Open http://localhost:5174/
```

Login with the admin credentials from the backend `.env` (default: `admin` / `admin`).

## Deployment

### Render (Backend)
- Service: Web Service
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Env Vars: set all from `master-backend/.env` (do NOT hardcode secrets)
  - `MASTER_FRONTEND_URLS`: set to your frontend domain(s)
  - `ADMIN_*`: secure values in production

### Netlify/Vercel (Frontend)
- Build: `npm run build`
- Preview: `vite preview`
- Set `VITE_MASTER_API_URL` and `VITE_DASHBOARD_WS_URL` to point to the deployed backend

## Troubleshooting
- `401 Unauthorized`: verify `Authorization: Bearer <token>` header is sent; re-login.
- WebSocket closes with code 1008: token missing/invalid; ensure frontend passes `token` query param.
- CORS blocked: update `MASTER_FRONTEND_URLS` to include your frontend origin.
- Agents not listing: ensure agents connect to `/ws/agent` with correct handshake payload.

## Security Tips
- Change `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `ADMIN_SECRET` for production.
- Reduce `ADMIN_TOKEN_TTL` if shorter sessions are desired.
- Avoid committing production secrets; use platform-managed env vars.
