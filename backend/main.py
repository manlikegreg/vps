from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import asyncio, os, sys, subprocess, logging, socket
from dotenv import load_dotenv
import secrets, time
import json
import websockets
from fastapi import Request, UploadFile, File

# Ensure Windows supports asyncio subprocesses
if sys.platform == 'win32':
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format='%(levelname)s:     %(message)s')

load_dotenv()
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')
ALLOWED_ORIGINS = [FRONTEND_URL]
# Hardcoded master control URL; change here when needed
MASTER_CONTROL_WS_URL = 'ws://localhost:9000/ws/agent'
AGENT_HTTP_BASE = os.getenv('AGENT_HTTP_BASE', 'http://localhost:8000')
SESSION_DIRS: dict[str, str] = {}

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin')
TOKEN_TTL_SECONDS = int(os.getenv('TOKEN_TTL_SECONDS', '86400'))
TOKENS: dict[str, float] = {}

class CommandRequest(BaseModel):
    command: str

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/login")
async def login(req: LoginRequest):
    try:
        if req.username == ADMIN_USERNAME and req.password == ADMIN_PASSWORD:
            token = secrets.token_urlsafe(32)
            TOKENS[token] = time.time() + TOKEN_TTL_SECONDS
            return {"token": token}
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)
    except Exception as e:
        logging.exception("Login failed")
        return JSONResponse({"error": f"Login failed: {e}"}, status_code=500)

@app.post("/execute")
async def execute(cmd: CommandRequest):
    command = cmd.command
    def run_cmd():
        if os.name == 'nt':
            return subprocess.run(['cmd.exe', '/c', command], capture_output=True, text=True)
        return subprocess.run(command, shell=True, capture_output=True, text=True)
    try:
        logging.info(f"REST execute: {command}")
        proc = await asyncio.to_thread(run_cmd)
        if proc.stdout:
            logging.info(proc.stdout.strip())
        if proc.stderr:
            logging.error(proc.stderr.strip())
        return {"command": command, "stdout": proc.stdout or "", "stderr": proc.stderr or "", "exit_code": proc.returncode}
    except Exception as e:
        logging.error(f"Failed to execute: {e}")
        return JSONResponse({"error": f"Failed to execute: {e}"}, status_code=500)

@app.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    token = request.query_params.get("token")
    dir_path = SESSION_DIRS.get(token or "", os.getcwd())
    try:
        name = os.path.basename(file.filename or "upload.bin")
        data = await file.read()
        out_path = os.path.join(dir_path, name)
        with open(out_path, "wb") as f:
            f.write(data)
        return {"saved": out_path, "size": len(data)}
    except Exception as e:
        return JSONResponse({"error": f"Upload failed: {e}"}, status_code=500)

@app.get("/stats")
async def stats(request: Request):
    token = request.query_params.get("token")
    dir_path = SESSION_DIRS.get(token or "", os.getcwd())
    try:
        items = []
        for name in os.listdir(dir_path):
            full = os.path.join(dir_path, name)
            try:
                st = os.stat(full)
                items.append({
                    "name": name,
                    "is_dir": os.path.isdir(full),
                    "size": int(st.st_size),
                    "modified": int(st.st_mtime),
                })
            except Exception:
                items.append({"name": name, "is_dir": os.path.isdir(full)})
        return {"current_dir": dir_path, "files": items}
    except Exception as e:
        return JSONResponse({"error": f"Stats failed: {e}"}, status_code=500)

@app.post("/upload_master")
async def upload_file_master(file: UploadFile = File(...)):
    try:
        name = os.path.basename(file.filename or "upload.bin")
        data = await file.read()
        out_path = os.path.join(current_agent_dir, name)
        with open(out_path, "wb") as f:
            f.write(data)
        return {"saved": out_path, "size": len(data)}
    except Exception as e:
        return JSONResponse({"error": f"Upload failed: {e}"}, status_code=500)

@app.get("/stats_master")
async def stats_master():
    dir_path = current_agent_dir
    try:
        items = []
        for name in os.listdir(dir_path):
            full = os.path.join(dir_path, name)
            try:
                st = os.stat(full)
                items.append({
                    "name": name,
                    "is_dir": os.path.isdir(full),
                    "size": int(st.st_size),
                    "modified": int(st.st_mtime),
                })
            except Exception:
                items.append({"name": name, "is_dir": os.path.isdir(full)})
        return {"current_dir": dir_path, "files": items}
    except Exception as e:
        return JSONResponse({"error": f"Stats failed: {e}"}, status_code=500)

@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    # Validate token from query params before accepting
    token = websocket.query_params.get("token") if hasattr(websocket, "query_params") else None
    now = time.time()
    if not token or token not in TOKENS or TOKENS[token] < now:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    current_dir = os.getcwd()
    SESSION_DIRS[token] = current_dir
    try:
        while True:
            msg = await websocket.receive_text()
            logging.info("Frontend : %s", msg)
            # Handle built-in directory changes so cwd persists across commands
            stripped = msg.strip()
            parts0 = stripped.split(maxsplit=1)
            head0 = parts0[0].lower() if parts0 else ""
            arg0 = parts0[1] if len(parts0) > 1 else None
            if head0 in ("cd", "chdir"):
                target = arg0.strip() if arg0 else None
                if target:
                    if target.lower().startswith("/d "):
                        target = target[3:].strip()
                    target = os.path.expandvars(os.path.expanduser(target))
                    target = target.strip().strip('"').strip("'")
                    if len(target) == 2 and target[1] == ":" and target[0].isalpha():
                        new_dir = f"{target}\\"
                    else:
                        new_dir = target if os.path.isabs(target) else os.path.abspath(os.path.join(current_dir, target))
                    if os.path.isdir(new_dir):
                        current_dir = new_dir
                        SESSION_DIRS[token] = current_dir
                        await websocket.send_json({"output": current_dir + "\n"})
                        await websocket.send_json({"exit_code": 0})
                    else:
                        await websocket.send_json({"error": "The system cannot find the path specified.\n"})
                        await websocket.send_json({"exit_code": 1})
                else:
                    await websocket.send_json({"output": current_dir + "\n"})
                    await websocket.send_json({"exit_code": 0})
                continue
            cmd_to_run = msg

            # Execute and stream command output
            if os.name == "nt":
                # Windows fallback: use threads with subprocess.Popen to avoid NotImplementedError
                def start_proc():
                    return subprocess.Popen(
                        ["cmd.exe", "/c", cmd_to_run],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        cwd=current_dir,
                    )
                proc = await asyncio.to_thread(start_proc)
                loop = asyncio.get_running_loop()
                queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
                def reader(stream, key):
                    try:
                        for line in stream:
                            loop.call_soon_threadsafe(queue.put_nowait, (key, line))
                    except Exception as e:
                        loop.call_soon_threadsafe(queue.put_nowait, ("error", f"[reader {key} failed: {e}\n]"))
                    finally:
                        loop.call_soon_threadsafe(queue.put_nowait, ("__done__", key))
                t1 = asyncio.create_task(asyncio.to_thread(reader, proc.stdout, "output"))
                t2 = asyncio.create_task(asyncio.to_thread(reader, proc.stderr, "error"))
                done_readers = 0
                while done_readers < 2:
                    key, payload = await queue.get()
                    if key == "__done__":
                        done_readers += 1
                        continue
                    await websocket.send_json({key: payload})
                await asyncio.gather(t1, t2)
                return_code = await asyncio.to_thread(proc.wait)
                await websocket.send_json({"exit_code": return_code})
            else:
                proc = await asyncio.create_subprocess_shell(
                    cmd_to_run,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=current_dir,
                )
                async def stream_reader(stream, key):
                    try:
                        while True:
                            line = await stream.readline()
                            if not line:
                                break
                            text = line.decode(errors="replace")
                            await websocket.send_json({key: text})
                    except Exception:
                        logging.exception("Streaming failed")
                await asyncio.gather(
                    stream_reader(proc.stdout, "output"),
                    stream_reader(proc.stderr, "error"),
                )
                return_code = await proc.wait()
                await websocket.send_json({"exit_code": return_code})

    except WebSocketDisconnect:
        logging.info("WebSocket disconnected")
    except Exception:
        logging.exception("WebSocket error")
    finally:
        if token:
            SESSION_DIRS.pop(token, None)



# Agent-to-Master connector
current_agent_dir = os.getcwd()

async def _send_line(ws, key, text):
    try:
        await ws.send(json.dumps({key: text}))
    except Exception:
        pass

async def _run_agent_command(cmd: str, ws):
    global current_agent_dir
    stripped = cmd.strip()
    parts0 = stripped.split(maxsplit=1)
    head0 = parts0[0].lower() if parts0 else ""
    arg0 = parts0[1] if len(parts0) > 1 else None
    if head0 in ("cd","chdir"):
        target = arg0.strip() if arg0 else None
        if target:
            if target.lower().startswith("/d "):
                target = target[3:].strip()
            target = os.path.expandvars(os.path.expanduser(target))
            target = target.strip().strip('"').strip("'")
            if len(target)==2 and target[1]==":" and target[0].isalpha():
                new_dir = f"{target}\\"
            else:
                new_dir = target if os.path.isabs(target) else os.path.abspath(os.path.join(current_agent_dir, target))
            if os.path.isdir(new_dir):
                current_agent_dir = new_dir
                await _send_line(ws, "output", current_agent_dir + "\n")
                await _send_line(ws, "exit_code", 0)
            else:
                await _send_line(ws, "error", "The system cannot find the path specified.\n")
                await _send_line(ws, "exit_code", 1)
        else:
            await _send_line(ws, "output", current_agent_dir + "\n")
            await _send_line(ws, "exit_code", 0)
        return

    if os.name == "nt":
        def start_proc():
            return subprocess.Popen(
                ["cmd.exe","/c", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=current_agent_dir,
            )
        proc = await asyncio.to_thread(start_proc)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str,str]] = asyncio.Queue()
        def reader(stream, key):
            try:
                for line in stream:
                    loop.call_soon_threadsafe(queue.put_nowait, (key, line))
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", f"[reader {key} failed: {e}\n]"))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("__done__", key))
        t1 = asyncio.create_task(asyncio.to_thread(reader, proc.stdout, "output"))
        t2 = asyncio.create_task(asyncio.to_thread(reader, proc.stderr, "error"))
        done_readers = 0
        while done_readers < 2:
            key, payload = await queue.get()
            if key == "__done__":
                done_readers += 1
                continue
            await _send_line(ws, key, payload)
        await asyncio.gather(t1, t2)
        code = await asyncio.to_thread(proc.wait)
        await _send_line(ws, "exit_code", code)
    else:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=current_agent_dir,
        )
        async def stream_reader(stream, key):
            try:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode(errors="replace")
                    await _send_line(ws, key, text)
            except Exception:
                logging.exception("Agent streaming failed")
        await asyncio.gather(
            stream_reader(proc.stdout, "output"),
            stream_reader(proc.stderr, "error"),
        )
        code = await proc.wait()
        await _send_line(ws, "exit_code", code)

def _derive_identity_sync() -> tuple[str, str]:
    # Returns (agent_id, agent_name) derived from local system
    try:
        if os.name == 'nt':
            proc = subprocess.run(["cmd.exe", "/c", "whoami"], capture_output=True, text=True)
        else:
            proc = subprocess.run(["whoami"], capture_output=True, text=True)
        who = (proc.stdout or "").strip() or os.getenv("USERNAME") or os.getenv("USER") or "unknown"
    except Exception:
        who = os.getenv("USERNAME") or os.getenv("USER") or "unknown"
    host = os.getenv('COMPUTERNAME') or socket.gethostname() or 'host'
    base = f"agent-{host}-{who}".lower()
    safe = ''.join(ch if ch.isalnum() or ch in ('-', '_', '.') else '-' for ch in base)
    agent_id = safe.strip('-') or 'agent-unknown'
    agent_name = who
    return agent_id, agent_name

async def connect_master_control():
    last_log = 0.0
    while True:
        try:
            async with websockets.connect(MASTER_CONTROL_WS_URL, ping_interval=20, ping_timeout=20) as ws:
                try:
                    agent_id, agent_name = await asyncio.to_thread(_derive_identity_sync)
                    await ws.send(json.dumps({"agent_id": agent_id, "agent_name": agent_name, "http_base": AGENT_HTTP_BASE}))
                except Exception:
                    pass
                while True:
                    raw = await ws.recv()
                    try:
                        data = json.loads(raw)
                    except Exception:
                        data = {"command": raw}
                    cmd = data.get("command")
                    if cmd:
                        await _run_agent_command(cmd, ws)
        except Exception as e:
            now = time.time()
            if now - last_log >= 60:
                logging.error(f"Master connect failed: {e}")
                last_log = now
            await asyncio.sleep(2)

@app.on_event("startup")
async def _startup_connect_master():
    asyncio.create_task(connect_master_control())