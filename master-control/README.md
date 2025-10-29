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

## Master proxy (AGENT_HTTP_BASE)

The master backend proxies file operations (list/upload/download) to each agent over HTTP.
When an agent connects over WebSocket, it advertises `http_base` (from the agent's `AGENT_HTTP_BASE`).
The master calls the agent on these paths:
- `GET <http_base>/stats_master` → list current directory
- `POST <http_base>/upload_master` → upload a file
- `GET <http_base>/download_master?name=...` → download a file

Notes:
- `http_base` must be reachable from the master backend (e.g., `http://<agent-ip>:8000`).
- If it is not set or unreachable, terminal streaming still works, but file explorer, upload, and download are disabled (requests will 404/500 and the UI will show an empty list).
- To disable file features entirely, leave `AGENT_HTTP_BASE` empty or ensure the master cannot reach it.

## Multiple Master Control servers

Agents can connect to more than one Master server simultaneously.
To set this up on the agent:

1. Open `backend/main.py` in the agent project.
2. Locate the list `MASTER_CONTROL_WS_URLS` and add more endpoints:

```python
MASTER_CONTROL_WS_URLS = [
    MASTER_CONTROL_WS_URL,
    'wss://master-2.example.com/ws/agent',
    # 'wss://master-3.example.com/ws/agent',
]
```

The agent will maintain one WebSocket per URL with independent retry and 1‑minute log throttling.
All masters will see (and can control) the same agent. If you need to avoid conflicting commands,
operate from a single master at a time or add policy in the agent (queue/allowlist).

Line location: the URL array lives at `backend/main.py`, line 27. Waiting masters receive terminal messages like "[Queued] You are #N in queue" and updates as their turn approaches.

## Command conflict policy (queue/allowlist)

Current default:
- The agent executes commands as they arrive; if multiple masters send commands concurrently, their outputs may interleave. There is no global lock.

Options you can adopt (not enforced by default):
- Queue policy: serialize all commands through a single FIFO queue. Prevents conflicts but reduces parallelism.
- Allowlist policy: only accept commands from specific master URLs/hosts; ignore others. Useful for a primary/secondary setup.

Operational guidance today:
- Prefer operating from a single master at a time, or coordinate between masters.
- If you need strict isolation, we can add a simple global queue or allowlist in the agent on request.

## Agent connection URL (hardcoded)

Agents now use a hardcoded WebSocket URL for connecting to Master Control.
To change it:

1. Open `backend/main.py` in the agent project.
2. Find the line (backend/main.py, line 25):

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
