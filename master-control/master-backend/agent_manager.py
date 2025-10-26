import json
from typing import Dict, Any, List, Set
from fastapi import WebSocket
import asyncio
import aiofiles
import os

AGENTS_FILE = os.path.join(os.path.dirname(__file__), 'config', 'agents.json')

class AgentManager:
    def __init__(self) -> None:
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.dashboards: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
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

    async def register_agent(self, agent_id: str, name: str, http_base: str, ws: WebSocket) -> None:
        async with self._lock:
            self.agents[agent_id] = {"socket": ws, "name": name, "http_base": http_base}
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
            return [{"agent_id": aid, "name": info.get("name"), "http_base": info.get("http_base")} for aid, info in self.agents.items()]

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

    async def relay_output_to_dashboards(self, agent_id: str, output: str) -> None:
        await self._broadcast_to_dashboards({"type": "log", "agent_id": agent_id, "line": output})

    async def relay_exit_to_dashboards(self, agent_id: str, code: int) -> None:
        await self._broadcast_to_dashboards({"type": "exit", "agent_id": agent_id, "exit_code": code})

    async def get_agent_http_base(self, agent_id: str) -> str | None:
        async with self._lock:
            entry = self.agents.get(agent_id)
            return entry.get("http_base") if entry else None

manager = AgentManager()
