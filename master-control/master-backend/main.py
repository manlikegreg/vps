import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from agent_manager import manager
from ws_routes import router
from fastapi import UploadFile, File
import httpx

# Load environment variables from .env
load_dotenv()

app = FastAPI()

# Configure CORS using env
frontend_url = os.getenv("MASTER_FRONTEND_URL", "http://localhost:5173")
origins_env = os.getenv("MASTER_FRONTEND_URLS")
if origins_env:
    allowed_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
else:
    allowed_origins = [frontend_url, "http://localhost:5174"]

app.add_middleware(
     CORSMiddleware,
     allow_origins=allowed_origins,
     allow_credentials=True,
     allow_methods=["*"],
     allow_headers=["*"],
 )

# REST endpoint to list agents
@app.get('/agents')
async def list_agents():
    agents = await manager.get_agents()
    return JSONResponse(content=agents)

# Include WebSocket routes
app.include_router(router)

# --- Admin Auth Endpoints ---
from pydantic import BaseModel
from fastapi import Request, Depends, HTTPException, status
from auth import check_credentials, create_token, verify_token

class LoginBody(BaseModel):
    username: str
    password: str

@app.post('/admin/login')
async def admin_login(body: LoginBody):
    if not check_credentials(body.username, body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_token(body.username)
    return JSONResponse(content={"token": token, "token_type": "Bearer"})

def auth_required(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        tok = auth[7:].strip()
        if verify_token(tok):
            return True
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

@app.get('/admin/verify')
async def admin_verify(_: bool = Depends(auth_required)):
    return JSONResponse(content={"ok": True})

# Protect existing REST endpoints
@app.get('/agent/{agent_id}/stats')
async def agent_stats(agent_id: str, _: bool = Depends(auth_required)):
    http_base = await manager.get_agent_http_base(agent_id)
    if not http_base:
        return JSONResponse(status_code=404, content={"error": "Agent not found"})
    url = f"{http_base}/stats_master"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Proxy failed: {e}"})

@app.post('/agent/{agent_id}/upload')
async def agent_upload(agent_id: str, file: UploadFile = File(...), _: bool = Depends(auth_required)):
    http_base = await manager.get_agent_http_base(agent_id)
    if not http_base:
        return JSONResponse(status_code=404, content={"error": "Agent not found"})
    url = f"{http_base}/upload_master"
    try:
        data = await file.read()
        filename = file.filename or 'upload.bin'
        content_type = file.content_type or 'application/octet-stream'
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, files={'file': (filename, data, content_type)})
            return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Proxy failed: {e}"})