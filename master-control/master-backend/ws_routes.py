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
        await manager.register_agent(agent_id, agent_name, http_base, ws)

        # Stream messages from agent to dashboards
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                data = {"output": msg}

            if 'output' in data:
                await manager.relay_output_to_dashboards(agent_id, str(data['output']))
            elif 'line' in data:
                await manager.relay_output_to_dashboards(agent_id, str(data['line']))
            elif 'exit_code' in data:
                await manager.relay_exit_to_dashboards(agent_id, int(data['exit_code']))
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
            command = data.get('command')
            if target and command:
                ok = await manager.forward_command(target, command)
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
