import json
from typing import Dict, Any, List, Set
from fastapi import WebSocket
import asyncio
import aiofiles
import os
import uuid

AGENTS_FILE = os.path.join(os.path.dirname(__file__), 'config', 'agents.json')

class AgentManager:
    def __init__(self) -> None:
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.dashboards: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._pending_stats: Dict[str, asyncio.Future] = {}
        # Ensure config file exists
        os.makedirs(os.path.join(os.path.dirname(__file__), 'config'), exist_ok=True)
        if not os.path.exists(AGENTS_FILE):
            with open(AGENTS_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f)

    async def register_dashboard(self, ws: WebSocket) -> None:
        async with self._lock:
            self.dashboards.add(ws)
        await self.broadcast_agents()

    async def remove_dashboard(self, ws: WebSocket) -> None:
        async with self._lock:
            self.dashboards.discard(ws)

    async def register_agent(self, agent_id: str, name: str, http_base: str, ws: WebSocket, has_camera: bool = False) -> None:
        async with self._lock:
            self.agents[agent_id] = {"socket": ws, "name": name, "http_base": http_base, "has_camera": bool(has_camera)}
        await self.persist_agents()
        await self.broadcast_agents()

    async def remove_agent(self, agent_id: str) -> None:
        async with self._lock:
            if agent_id in self.agents:
                self.agents.pop(agent_id, None)
        await self.persist_agents()
        await self.broadcast_agents()

    async def persist_agents(self) -> None:
        agents_list = await self.get_agents()
        async with aiofiles.open(AGENTS_FILE, 'w') as f:
            await f.write(json.dumps(agents_list, indent=2))

    async def get_agents(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return [{"agent_id": aid, "name": info.get("name"), "http_base": info.get("http_base"), "has_camera": bool(info.get("has_camera"))} for aid, info in self.agents.items()]

    async def broadcast_agents(self) -> None:
        payload = {"type": "agents", "agents": await self.get_agents()}
        await self._broadcast_to_dashboards(payload)

    async def _broadcast_to_dashboards(self, payload: Dict[str, Any]) -> None:
        stale: List[WebSocket] = []
        for ws in list(self.dashboards):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            await self.remove_dashboard(ws)

    async def forward_command(self, agent_id: str, command: str) -> bool:
        async with self._lock:
            entry = self.agents.get(agent_id)
            ws = entry.get("socket") if entry else None
        if not ws:
            return False
        try:
            await ws.send_json({"command": command})
            return True
        except Exception:
            return False

    async def forward_json(self, agent_id: str, payload: Dict[str, Any]) -> bool:
        async with self._lock:
            entry = self.agents.get(agent_id)
            ws = entry.get("socket") if entry else None
        if not ws:
            return False
        try:
            await ws.send_json(payload)
            return True
        except Exception:
            return False

    async def request_stats(self, agent_id: str) -> Dict[str, Any]:
        async with self._lock:
            entry = self.agents.get(agent_id)
            ws = entry.get("socket") if entry else None
        if not ws:
            return {"error": "Agent not connected"}
        req_id = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_stats[req_id] = fut
        try:
            await ws.send_json({"type": "stats_request", "request_id": req_id})
        except Exception as e:
            self._pending_stats.pop(req_id, None)
            return {"error": f"Failed to send request: {e}"}
        try:
            data = await asyncio.wait_for(fut, timeout=10.0)
            return data if isinstance(data, dict) else {"data": data}
        except asyncio.TimeoutError:
            self._pending_stats.pop(req_id, None)
            return {"error": "Timed out waiting for stats"}

    async def complete_stats_request(self, request_id: str, payload: Dict[str, Any]) -> None:
        fut = self._pending_stats.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(payload)

    async def relay_output_to_dashboards(self, agent_id: str, output: str) -> None:
        await self._broadcast_to_dashboards({"type": "log", "agent_id": agent_id, "line": output})

    async def relay_exit_to_dashboards(self, agent_id: str, code: int) -> None:
        await self._broadcast_to_dashboards({"type": "exit", "agent_id": agent_id, "exit_code": code})

    async def relay_screen_to_dashboards(self, agent_id: str, frame: Dict[str, Any]) -> None:
        payload = {"type": "screen_frame", "agent_id": agent_id, **frame}
        await self._broadcast_to_dashboards(payload)

    async def relay_camera_to_dashboards(self, agent_id: str, frame: Dict[str, Any]) -> None:
        payload = {"type": "camera_frame", "agent_id": agent_id, **frame}
        await self._broadcast_to_dashboards(payload)

    async def get_agent_http_base(self, agent_id: str) -> str | None:
        async with self._lock:
            entry = self.agents.get(agent_id)
            return entry.get("http_base") if entry else None

manager = AgentManager()
