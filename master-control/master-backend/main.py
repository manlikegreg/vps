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
frontend_url = os.getenv("MASTER_FRONTEND_URL", "http://localhost:5174")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST endpoint to list agents
@app.get('/agents')
async def list_agents():
    agents = await manager.get_agents()
    return JSONResponse(content=agents)

@app.get('/agent/{agent_id}/stats')
async def agent_stats(agent_id: str):
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
async def agent_upload(agent_id: str, file: UploadFile = File(...)):
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

# Include WebSocket routes
app.include_router(router)